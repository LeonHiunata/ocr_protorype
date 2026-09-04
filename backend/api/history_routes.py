from flask import Blueprint, jsonify, request, Response
import time
import json
import csv
import io
from datetime import datetime, timedelta, timezone
from middleware.error_handler import APIError
from core.history_service import load_history, save_history

history_bp = Blueprint('history', __name__)

@history_bp.route('/send-to-database', methods=['POST'])
def send_to_database():
    """
    Endpoint menerima data gabungan OCR + GPS, menyimpan ke file history JSON, dan log console.
    """
    try:
        payload = request.get_json(force=True)
        ocr_data  = payload.get('ocr_data', {})
        gps_data  = payload.get('gps_data', {})
        lokasi    = payload.get('lokasi', 'N/A')
        tipe_container = payload.get('tipe_container', 'N/A')
        image_uri = payload.get('image_uri', '')

        now_wib = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=7))
        ).strftime('%Y-%m-%d %H:%M:%S WIB')

        record = {
            'id': int(time.time() * 1000),
            'tipe_container': tipe_container,
            'nomor_container': ocr_data.get('Nomor Container :', 'N/A'),
            'serial_number': ocr_data.get('Serial Number :', 'N/A'),
            'check_number': ocr_data.get('Check Number :', 'N/A'),
            'grade': ocr_data.get('Grade', 'N/A'),
            'lokasi_slot': lokasi,
            'waktu': gps_data.get('time_wib') or now_wib,
            'image_uri': image_uri
        }

        history = load_history()
        history.insert(0, record)
        save_history(history)

        print("\n" + "=" * 60)
        print("  DATA CONTAINER TERSIMPAN KE DATABASE")
        print("=" * 60)
        print(f"  Nomor Container : {record['nomor_container']}")
        print(f"  Tipe Container  : {record['tipe_container']}")
        print(f"  Lokasi Slot     : {record['lokasi_slot']}")
        print(f"  Waktu WIB       : {record['waktu']}")
        print("=" * 60 + "\n")

        return jsonify({'success': True, 'message': 'Data berhasil disimpan ke database.', 'record': record})

    except Exception as e:
        raise APIError(f'Terjadi kesalahan saat menyimpan data: {str(e)}', 500)

@history_bp.route('/api/save-record', methods=['POST'])
def api_save_record():
    """Endpoint langsung menyimpan record baru."""
    return send_to_database()

@history_bp.route('/api/history', methods=['GET', 'DELETE'])
def api_history():
    """Endpoint membaca atau menghapus seluruh data riwayat."""
    if request.method == 'DELETE':
        save_history([])
        return jsonify({'success': True, 'message': 'Riwayat berhasil dibersihkan.'})
    
    history = load_history()
    return jsonify({'success': True, 'history': history, 'total': len(history)})

@history_bp.route('/api/history/<int:record_id>', methods=['DELETE'])
def api_delete_history_item(record_id):
    """Endpoint menghapus 1 item record riwayat berdasarkan ID."""
    history = load_history()
    new_history = [item for item in history if str(item.get('id')) != str(record_id)]
    save_history(new_history)
    return jsonify({'success': True, 'message': 'Record riwayat berhasil dihapus.'})

@history_bp.route('/api/history/delete-selected', methods=['POST'])
def api_delete_selected_history():
    """Endpoint menghapus beberapa item record riwayat terpilih."""
    data = request.json or {}
    raw_ids = data.get('ids', [])
    ids_to_delete = set(str(i) for i in raw_ids)
    
    history = load_history()
    new_history = [item for item in history if str(item.get('id')) not in ids_to_delete]
    save_history(new_history)
    return jsonify({'success': True, 'message': f'{len(ids_to_delete)} record berhasil dihapus.'})

@history_bp.route('/api/export/<format_type>', methods=['GET'])
def api_export(format_type):
    """Export data riwayat ke format CSV atau JSON."""
    history = load_history()
    
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H-%M-%S')
    base_filename = f"ListContainer[{date_str}][{time_str}]"
    
    def generate_custom_id(item):
        import re
        waktu = item.get('waktu', '')
        grade = item.get('grade', '')
        serial = item.get('serial_number', '')
        tipe = item.get('tipe_container', '20ft')
        
        grade_letter = 'B'
        if 'A' in str(grade).upper():
            grade_letter = 'A'
        elif 'B' in str(grade).upper():
            grade_letter = 'B'
        elif serial and len(serial) >= 2 and serial[:2].isdigit():
            if int(serial[:2]) >= 30:
                grade_letter = 'A'
                
        size_prefix = '4' if '40' in str(tipe) else '2'
        
        date_time_part = "000000000000"
        digits = re.findall(r'\d+', waktu)
        if len(digits) >= 6:
            YYYY, MM, DD, HH, MIN, SS = digits[:6]
            YY = YYYY[-2:]
            date_time_part = f"{DD}{MM}{YY}{HH}{MIN}{SS}"
            
        return f"{grade_letter}{size_prefix}{date_time_part}"
    
    if format_type.lower() in ('excel', 'xlsx', 'xls'):
        html_out = "<html><head><meta charset='utf-8'></head><body><table border='1'>"
        html_out += "<tr style='background-color:#1e293b;color:#ffffff;'><th>ID</th><th>Tanggal</th><th>Jam</th><th>Tipe Container</th><th>Nomor Container</th><th>Serial Number</th><th>Check Number</th><th>Grade</th><th>Lokasi Slot Depo</th></tr>"
        for item in history:
            custom_id = generate_custom_id(item)
            waktu = item.get('waktu', '')
            parts = waktu.split(' ')
            tanggal = parts[0] if len(parts) > 0 else '-'
            jam = ' '.join(parts[1:]) if len(parts) > 1 else '-'
            
            html_out += f"<tr><td>{custom_id}</td><td>{tanggal}</td><td>{jam}</td><td>{item.get('tipe_container','')}</td><td>{item.get('nomor_container','')}</td><td>{item.get('serial_number','')}</td><td>{item.get('check_number','')}</td><td>{item.get('grade','')}</td><td>{item.get('lokasi_slot','')}</td></tr>"
        html_out += "</table></body></html>"

        response = Response(html_out.encode('utf-8'), mimetype='application/vnd.ms-excel')
        response.headers['Content-Disposition'] = f'attachment; filename="{base_filename}.xls"'
        return response

    elif format_type.lower() == 'json':
        clean_history = []
        for item in history:
            clean_item = {k: v for k, v in item.items() if k not in ('image_uri', 'waktu')}
            clean_item['id'] = generate_custom_id(item)
            waktu = item.get('waktu', '')
            parts = waktu.split(' ')
            clean_item['tanggal'] = parts[0] if len(parts) > 0 else '-'
            clean_item['jam'] = ' '.join(parts[1:]) if len(parts) > 1 else '-'
            
            # Reorder keys slightly so they are near the top
            ordered_item = {'id': clean_item['id'], 'tanggal': clean_item['tanggal'], 'jam': clean_item['jam']}
            ordered_item.update(clean_item)
            clean_history.append(ordered_item)
            
        response = Response(
            json.dumps(clean_history, indent=2, ensure_ascii=False),
            mimetype='application/json'
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{base_filename}.json"'
        return response

    elif format_type.lower() == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = [
            "ID", "Tanggal", "Jam", "Tipe Container", "Nomor Container", 
            "Serial Number", "Check Number", "Grade", "Lokasi Slot Depo"
        ]
        writer.writerow(headers)

        for item in history:
            waktu = item.get('waktu', '')
            parts = waktu.split(' ')
            tanggal = parts[0] if len(parts) > 0 else '-'
            jam = ' '.join(parts[1:]) if len(parts) > 1 else '-'
            
            writer.writerow([
                generate_custom_id(item),
                tanggal,
                jam,
                item.get('tipe_container', ''),
                item.get('nomor_container', ''),
                item.get('serial_number', ''),
                item.get('check_number', ''),
                item.get('grade', ''),
                item.get('lokasi_slot', '')
            ])

        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename="{base_filename}.csv"'
        return response

    raise APIError('Format export tidak didukung (gunakan excel, csv, atau json).', 400)
