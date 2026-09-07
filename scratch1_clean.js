
        // ─── State Management ───
        const appState = {
            currentStep: 1,
            completedSteps: new Set(),
            selectedSize: null, // '20ft' or '40ft'
            ocrData: null,
            ocrImageUri: null,
            gpsData: null,
            webcamStream: null,
            historyLogs: [],
            isFinished: false,
            zoomTarget: 'ALL'
        };

        function toggleZoom() {
            if (appState.gpsData && appState.gpsData.detected_slot) {
                const slot = appState.gpsData.detected_slot.replace('SLOT ', '');
                const block = slot.charAt(0);
                if (appState.zoomTarget === block) {
                    appState.zoomTarget = 'ALL';
                    showToast('Zoom dikembalikan ke seluruh area', 'info');
                } else {
                    appState.zoomTarget = block;
                    showToast('Zoom ke Blok ' + block, 'success');
                }
            } else {
                appState.zoomTarget = 'ALL';
                showToast('Belum ada slot terdeteksi untuk di-zoom', 'warning');
            }
        }

        // ─── Real-Time Depo Mapping Canvas Engine ───
        if (window.proj4) {
            proj4.defs("EPSG:32748", "+proj=utm +zone=48 +south +datum=WGS84 +units=m +no_defs");
            proj4.defs("EPSG:4326", "+proj=longlat +datum=WGS84 +no_defs");
        }

        const REF_LON = 106.88178028, REF_LAT = -6.11260706;
        const refUTM = window.proj4 ? proj4("EPSG:4326", "EPSG:32748", [REF_LON, REF_LAT]) : [708241.531, 9323986.322];
        const REF_UTM_X = refUTM[0], REF_UTM_Y = refUTM[1];
        const CONTAINER_LENGTH = 6.0, CONTAINER_WIDTH = 3.0, ROTATION_DEG = 53.83;

        const boundaryPointsUTM = [
            [106.88178028, -6.11260706], [106.88190898, -6.11251261],
            [106.88187588, -6.11246944], [106.88189726, -6.11245381],
            [106.88185392, -6.11239707], [106.88170742, -6.11250445]
        ].map(pt => window.proj4 ? proj4("EPSG:4326", "EPSG:32748", pt) : [708241.5, 9323986.3]);

        function computeRotatedPolygon() {
            const angle = ROTATION_DEG * (Math.PI / 180);
            const polygon = [];
            let minRx = Infinity, maxRx = -Infinity, minRy = Infinity, maxRy = -Infinity;
            for (const [uX, uY] of boundaryPointsUTM) {
                const dx = uX - REF_UTM_X, dy = uY - REF_UTM_Y;
                const rx = dx * Math.cos(angle) - dy * Math.sin(angle);
                const ry = dx * Math.sin(angle) + dy * Math.cos(angle);
                polygon.push({ x: rx, y: ry });
                minRx = Math.min(minRx, rx); maxRx = Math.max(maxRx, rx);
                minRy = Math.min(minRy, ry); maxRy = Math.max(maxRy, ry);
            }
            return { polygon, minRx, maxRx, minRy, maxRy };
        }

        function getColumnLetter(colIndex) {
            if (colIndex < 0) return "-" + getColumnLetter(-colIndex - 1);
            let temp, letter = '';
            while (colIndex >= 0) {
                temp = colIndex % 26;
                letter = String.fromCharCode(temp + 65) + letter;
                colIndex = Math.floor((colIndex - temp) / 26) - 1;
            }
            return letter;
        }

        function pointInPolygon(point, vs, eps = 0.5) {
            let x = point.x, y = point.y;
            let inside = false;
            for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
                let xi = vs[i].x, yi = vs[i].y;
                let xj = vs[j].x, yj = vs[j].y;
                const dxSeg = xj - xi, dySeg = yj - yi;
                const lenSq = dxSeg * dxSeg + dySeg * dySeg;
                if (lenSq > 0) {
                    const t = Math.max(0, Math.min(1, ((x - xi) * dxSeg + (y - yi) * dySeg) / lenSq));
                    const nearX = xi + t * dxSeg, nearY = yi + t * dySeg;
                    const distSq = (x - nearX) ** 2 + (y - nearY) ** 2;
                    if (distSq <= eps * eps) return true;
                }
                let intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }
            return inside;
        }

        function isCellFullyInPolygon(cx, cy, rw, rh, poly) {
            const corners = [
                { x: cx, y: cy }, { x: cx + rw, y: cy },
                { x: cx + rw, y: cy + rh }, { x: cx, y: cy + rh }
            ];
            return corners.every(corner => pointInPolygon(corner, poly));
        }

        function drawDepoGrid() {
            const gridCanvas = document.getElementById('depoGridCanvas');
            if (!gridCanvas || appState.currentStep !== 3) return;
            const ctx = gridCanvas.getContext('2d');
            const polygonData = computeRotatedPolygon();
            if (!polygonData) return;
            const { polygon, minRx, maxRx, minRy, maxRy } = polygonData;

            let viewMinX = minRx;
            let viewMaxX = maxRx;
            let viewMinY = minRy;
            let viewMaxY = maxRy;

            if (appState.zoomTarget === 'B') {
                viewMaxX = minRx + 6.0;
            } else if (appState.zoomTarget === 'A') {
                viewMinX = minRx + 6.0;
                viewMaxX = minRx + 12.0;
            }

            const padding = Math.max((viewMaxX - viewMinX) * 0.1, (viewMaxY - viewMinY) * 0.1, 4);
            viewMinX -= padding;
            viewMaxX += padding;
            viewMinY -= padding;
            viewMaxY += padding;

            const viewWidth = viewMaxX - viewMinX;
            const viewHeight = viewMaxY - viewMinY;
            const aspectRatio = viewHeight / viewWidth;

            const targetWidth = 1200;
            const targetHeight = Math.round(targetWidth * aspectRatio);

            if (gridCanvas.width !== targetWidth || gridCanvas.height !== targetHeight) {
                gridCanvas.width = targetWidth;
                gridCanvas.height = targetHeight;
            }

            const scale = gridCanvas.width / viewWidth;
            const mapX = (x) => (x - viewMinX) * scale;
            const mapY = (y) => (viewMaxY - y) * scale;

            ctx.clearRect(0, 0, gridCanvas.width, gridCanvas.height);

            // Draw Boundary Polygon
            ctx.beginPath();
            ctx.moveTo(mapX(polygon[0].x), mapY(polygon[0].y));
            for (let i = 1; i < polygon.length; i++) ctx.lineTo(mapX(polygon[i].x), mapY(polygon[i].y));
            ctx.closePath();
            ctx.fillStyle = "rgba(234, 179, 8, 0.16)"; ctx.fill();
            ctx.lineWidth = 4; ctx.strokeStyle = "#eab308"; ctx.stroke();

            const customSlots = [];
            // Block B (Left, vertical stack of horizontal containers)
            for (let r = 0; r < 6; r++) {
                customSlots.push({ label: 'B' + (r + 1), cx: minRx, cy: minRy + r * 3.0, w: 6.0, h: 3.0, block: 'B' });
            }
            // Block A (Right, 3 rows of 2 vertical containers)
            for (let r = 0; r < 3; r++) {
                customSlots.push({ label: 'A' + (r * 2 + 1), cx: minRx + 6.0, cy: minRy + r * 6.0, w: 3.0, h: 6.0, block: 'A' });
                customSlots.push({ label: 'A' + (r * 2 + 2), cx: minRx + 9.0, cy: minRy + r * 6.0, w: 3.0, h: 6.0, block: 'A' });
            }

            let targetRotatedX = null, targetRotatedY = null;
            if (appState.gpsData && appState.gpsData.easting && appState.gpsData.northing) {
                const dx = appState.gpsData.easting - REF_UTM_X;
                const dy = appState.gpsData.northing - REF_UTM_Y;
                const angleRad = ROTATION_DEG * (Math.PI / 180);
                targetRotatedX = dx * Math.cos(angleRad) - dy * Math.sin(angleRad);
                targetRotatedY = dx * Math.sin(angleRad) + dy * Math.cos(angleRad);
            }

            let autoDetectedSlot = null;

            for (const slot of customSlots) {
                const { label: slotLabel, cx, cy, w: cWidth, h: cHeight, block } = slot;

                const eps = 0.2;
                let isTargetCell = false;
                if (targetRotatedX !== null && targetRotatedY !== null) {
                    if (targetRotatedX >= cx - eps && targetRotatedX <= cx + cWidth + eps &&
                        targetRotatedY >= cy - eps && targetRotatedY <= cy + cHeight + eps) {
                        isTargetCell = true;
                        autoDetectedSlot = slotLabel;
                    }
                }

                const px = mapX(cx);
                const py = mapY(cy + cHeight);
                const pWidth = cWidth * scale;
                const pHeight = cHeight * scale;

                    ctx.beginPath();
                    ctx.rect(px, py, pWidth, pHeight);

                    if (isTargetCell) {
                        ctx.fillStyle = "#3a9542"; ctx.strokeStyle = "#4dc257"; ctx.lineWidth = 4;
                    } else {
                        ctx.fillStyle = "#f97316"; ctx.strokeStyle = "#c2410c"; ctx.lineWidth = 2.5;
                    }
                    ctx.fill(); ctx.stroke();

                    // Circle Badge
                    const circleRadius = Math.min(pWidth, pHeight) * 0.40;
                    ctx.beginPath();
                    ctx.arc(px + pWidth / 2, py + pHeight / 2, circleRadius, 0, Math.PI * 2);
                    ctx.fillStyle = isTargetCell ? "#2e7735" : "rgba(255, 255, 255, 0.22)";
                    ctx.fill();
                    ctx.strokeStyle = isTargetCell ? "#4dc257" : "rgba(255, 255, 255, 0.6)";
                    ctx.lineWidth = isTargetCell ? 3 : 1.5;
                    ctx.stroke();

                    // Text
                    const fontSize = Math.max(22, Math.floor(pHeight * 0.45));
                    ctx.font = `900 ${fontSize}px 'Inter', sans-serif`;
                    ctx.textAlign = "center"; ctx.textBaseline = "middle";

                    ctx.strokeStyle = "rgba(0, 0, 0, 0.88)"; ctx.lineWidth = 5;
                    ctx.strokeText(slotLabel, px + pWidth / 2, py + pHeight / 2);
                    ctx.fillStyle = "#ffffff";
                    ctx.fillText(slotLabel, px + pWidth / 2, py + pHeight / 2);
            }

            // Draw Trail
            if (appState.gpsData && appState.gpsData.trail && appState.gpsData.trail.length > 1) {
                const angleRad = ROTATION_DEG * (Math.PI / 180);
                ctx.beginPath();
                let first = true;
                appState.gpsData.trail.forEach(pt => {
                    if (!pt || !pt.easting) return;
                    const dx = pt.easting - REF_UTM_X, dy = pt.northing - REF_UTM_Y;
                    const rx = dx * Math.cos(angleRad) - dy * Math.sin(angleRad);
                    const ry = dx * Math.sin(angleRad) + dy * Math.cos(angleRad);
                    const tX = mapX(rx), tY = mapY(ry);
                    if (first) { ctx.moveTo(tX, tY); first = false; }
                    else { ctx.lineTo(tX, tY); }
                });
                ctx.strokeStyle = "rgba(56, 189, 248, 0.9)"; ctx.lineWidth = 5;
                ctx.setLineDash([8, 5]); ctx.stroke(); ctx.setLineDash([]);
            }

            // Draw Moving Rover Beacon Marker
            if (targetRotatedX !== null && targetRotatedY !== null) {
                const px = mapX(targetRotatedX), py = mapY(targetRotatedY);
                const pulseR = Math.max(16, gridCanvas.width * 0.024) + Math.sin(Date.now() / 250.0) * 4;

                ctx.beginPath(); ctx.arc(px, py, pulseR, 0, Math.PI * 2);
                ctx.fillStyle = "rgba(239, 68, 68, 0.4)"; ctx.fill();

                ctx.beginPath(); ctx.arc(px, py, Math.max(10, gridCanvas.width * 0.014), 0, Math.PI * 2);
                ctx.fillStyle = "#c8102e"; ctx.fill();
                ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3; ctx.stroke();

                ctx.fillStyle = "#ffffff";
                ctx.font = `bold ${Math.max(12, Math.floor(gridCanvas.width * 0.017))}px Inter, sans-serif`;
                ctx.textAlign = "center"; ctx.textBaseline = "bottom";
                ctx.fillText("ROVER 📍", px, py - pulseR - 4);
            }

            if (autoDetectedSlot) {
                document.getElementById('gps-val-slot').textContent = "SLOT " + autoDetectedSlot;
                if (appState.gpsData) appState.gpsData.detected_slot = "SLOT " + autoDetectedSlot;
            }
        }

        // Animation Loop for Real-Time Canvas Mapping
        function animateCanvas() {
            if (appState.currentStep === 3) {
                drawDepoGrid();
            }
            requestAnimationFrame(animateCanvas);
        }
        requestAnimationFrame(animateCanvas);

        // ─── Theme Management ───
        function toggleTheme() {
            const body = document.body;
            const icon = document.getElementById('theme-icon');
            if (body.classList.contains('light-theme')) {
                body.classList.remove('light-theme');
                if (icon) icon.className = 'fa-solid fa-moon';
                localStorage.setItem('theme', 'dark');
            } else {
                body.classList.add('light-theme');
                if (icon) icon.className = 'fa-solid fa-sun';
                localStorage.setItem('theme', 'light');
            }
        }

        function initTheme() {
            const savedTheme = localStorage.getItem('theme');
            const icon = document.getElementById('theme-icon');
            if (savedTheme === 'dark') {
                document.body.classList.remove('light-theme');
                if (icon) icon.className = 'fa-solid fa-moon';
            } else {
                document.body.classList.add('light-theme');
                if (icon) icon.className = 'fa-solid fa-sun';
            }
        }

        // ─── Initialization ───
        document.addEventListener('DOMContentLoaded', () => {
            initTheme();
            updateStepUI();
            fetchGPSStatus();
            loadHistoryLogs();

            // Start live GPS telemetry update loop
            setInterval(fetchLiveLocation, 1000);
        });

        // ─── Step Navigation ───
        function updateStepUI() {
            // Update Stepper progress bar width
            const progressPct = ((appState.currentStep - 1) / 4) * 100;
            document.getElementById('stepper-progress').style.width = `${progressPct}%`;

            // Update step bubbles & views
            for (let i = 1; i <= 5; i++) {
                const itemEl = document.getElementById(`step-nav-${i}`);
                const viewEl = document.getElementById(`step-view-${i}`);

                itemEl.classList.remove('active', 'completed', 'locked');
                viewEl.classList.remove('active');

                if (i === appState.currentStep) {
                    itemEl.classList.add('active');
                    viewEl.classList.add('active');
                } else if (!canAccessStep(i)) {
                    itemEl.classList.add('locked');
                } else if (appState.completedSteps.has(i)) {
                    itemEl.classList.add('completed');
                }
            }
        }

        function canAccessStep(targetStep) {
            if (appState.isFinished && targetStep !== 5) return false;

            if (targetStep === 1) return true;
            if (targetStep === 2) return appState.selectedSize !== null;
            if (targetStep === 3) return appState.ocrData !== null;
            if (targetStep === 4) return appState.gpsData !== null;
            if (targetStep === 5) return true;
            return false;
        }

        function goToStep(stepNum) {
            if (!canAccessStep(stepNum)) {
                showToast('Selesaikan langkah sebelumnya terlebih dahulu.', 'warning');
                return;
            }

            // Stop webcam stream when moving away from Step 2
            if (appState.currentStep === 2 && stepNum !== 2) {
                stopCamera();
            }

            appState.currentStep = stepNum;
            updateStepUI();

            if (stepNum === 3) {
                refreshGPSData();
                drawDepoGrid();
            } else if (stepNum === 4) {
                renderSummaryCard();
            } else if (stepNum === 5) {
                loadHistoryLogs();
            }
        }

        // ─── Langkah 1: Selection Logic ───
        function selectContainerSize(size) {
            appState.selectedSize = size;

            document.getElementById('size-card-20ft').classList.toggle('selected', size === '20ft');
            document.getElementById('size-card-40ft').classList.toggle('selected', size === '40ft');

            document.getElementById('btn-next-step1').disabled = false;
            appState.completedSteps.add(1);
            updateStepUI();

            showToast(`Ukuran kontainer dipilih: ${size}`, 'info');
        }

        // ─── Langkah 2: Camera & OCR Processing ───
        function switchMediaTab(tab) {
            document.getElementById('tab-btn-camera').classList.toggle('active', tab === 'camera');
            document.getElementById('tab-btn-file').classList.toggle('active', tab === 'file');

            document.getElementById('media-tab-camera').style.display = tab === 'camera' ? 'flex' : 'none';
            document.getElementById('media-tab-file').style.display = tab === 'file' ? 'flex' : 'none';

            if (tab !== 'camera') {
                stopCamera();
            }
        }

        async function startCamera() {
            try {
                // Hide snapshot preview if previously visible
                const snapImg = document.getElementById('camera-snapshot-img');
                if (snapImg) snapImg.style.display = 'none';

                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
                });
                appState.webcamStream = stream;

                const videoEl = document.getElementById('webcam-stream');
                videoEl.srcObject = stream;
                videoEl.style.display = 'block';

                document.getElementById('camera-placeholder').style.display = 'none';
                document.getElementById('btn-start-cam').style.display = 'none';
                document.getElementById('btn-capture-cam').style.display = 'inline-flex';
                showToast('Kamera berhasil diaktifkan.', 'info');
            } catch (err) {
                showToast(`Gagal membuka kamera: ${err.message}`, 'danger');
            }
        }

        function stopCamera() {
            if (appState.webcamStream) {
                appState.webcamStream.getTracks().forEach(track => track.stop());
                appState.webcamStream = null;
            }
            const videoEl = document.getElementById('webcam-stream');
            if (videoEl) videoEl.style.display = 'none';

            const btnCapture = document.getElementById('btn-capture-cam');
            if (btnCapture) btnCapture.style.display = 'none';

            const btnStart = document.getElementById('btn-start-cam');
            if (btnStart) btnStart.style.display = 'inline-flex';

            const placeholder = document.getElementById('camera-placeholder');
            if (placeholder) placeholder.style.display = 'block';
        }

        function captureAndOCR() {
            const videoEl = document.getElementById('webcam-stream');
            const canvasEl = document.getElementById('capture-canvas');

            if (!videoEl || videoEl.readyState !== 4) {
                showToast('Stream kamera belum siap.', 'warning');
                return;
            }

            canvasEl.width = videoEl.videoWidth;
            canvasEl.height = videoEl.videoHeight;
            const ctx = canvasEl.getContext('2d');
            ctx.drawImage(videoEl, 0, 0);

            const dataUri = canvasEl.toDataURL('image/jpeg', 0.9);

            // 1. Matikan kamera stream secara langsung!
            stopCamera();

            // 2. Tampilkan pratinjau snapshot foto hasil jepretan secara langsung!
            document.getElementById('camera-placeholder').style.display = 'none';
            const snapImg = document.getElementById('camera-snapshot-img');
            if (snapImg) {
                snapImg.src = dataUri;
                snapImg.style.display = 'block';
            }

            processOCRImage(dataUri);
        }

        function handleFileUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = (e) => {
                processOCRImage(e.target.result);
            };
            reader.readAsDataURL(file);
        }

        async function processOCRImage(base64ImageUri) {
            showToast('Menjalankan pemrosesan OCR LLM...', 'info');

            try {
                const response = await fetch('/process-camera', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: base64ImageUri, tolerance: 100 })
                });

                const data = await response.json();
                if (!response.ok || data.error) {
                    showToast(data.error || 'Gagal memproses gambar OCR.', 'danger');
                    return;
                }

                appState.ocrData = data.results;
                appState.ocrImageUri = data.image_uri || base64ImageUri;
                appState.rawImageUri = base64ImageUri; // Save raw image to state

                // Render OCR details
                document.getElementById('img-preview-original').src = base64ImageUri;
                document.getElementById('img-preview-annotated').src = appState.ocrImageUri;

                document.getElementById('res-serial').value = data.results['Serial Number :'] || '';
                document.getElementById('res-check').value = data.results['Check Number :'] || '';
                updateContainerNumber();

                const gradeStr = data.results['Grade'] || 'Grade : B';
                const gradeBadge = document.getElementById('res-grade-badge');
                gradeBadge.textContent = gradeStr;
                gradeBadge.className = 'grade-badge ' + (gradeStr.includes('A') ? 'a' : gradeStr.includes('B') ? 'b' : 'c');

                document.getElementById('ocr-results-container').style.display = 'block';
                document.getElementById('btn-retake-ocr').style.display = 'inline-flex';
                document.getElementById('btn-next-step2').disabled = false;

                appState.completedSteps.add(2);
                updateStepUI();

                showToast('Deteksi OCR Berhasil!', 'success');
            } catch (err) {
                showToast(`Terjadi kesalahan jaringan OCR: ${err.message}`, 'danger');
            }
        }

        function updateContainerNumber() {
            const serialInput = document.getElementById('res-serial');
            const checkInput = document.getElementById('res-check');
            const containerDisplay = document.getElementById('res-no-container');

            let serialStr = serialInput.value.trim();
            if (serialStr === '-' || serialStr === 'N/A') serialStr = '';
            let checkStr = checkInput.value.trim();
            if (checkStr === '-' || checkStr === 'N/A') checkStr = '';

            const newContainerNumber = "SPNU" + serialStr + checkStr;
            containerDisplay.textContent = newContainerNumber;

            // Calculate Adaptive Grade
            let gradeStr = 'Grade : Unknown';
            if (serialStr.length >= 2) {
                const prefixInt = parseInt(serialStr.substring(0, 2), 10);
                if (!isNaN(prefixInt)) {
                    gradeStr = prefixInt < 30 ? 'Grade : B' : 'Grade : A';
                }
            }
            const gradeBadge = document.getElementById('res-grade-badge');
            if (gradeBadge) {
                gradeBadge.textContent = gradeStr;
                gradeBadge.className = 'grade-badge ' + (gradeStr.includes('A') ? 'a' : gradeStr.includes('B') ? 'b' : 'c');
            }

            if (appState.ocrData) {
                appState.ocrData['Nomor Container :'] = newContainerNumber;
                appState.ocrData['Serial Number :'] = serialStr;
                appState.ocrData['Check Number :'] = checkStr;
                appState.ocrData['Grade'] = gradeStr;
            }
        }

        function resetStep2Data() {
            appState.ocrData = null;
            appState.ocrImageUri = null;

            document.getElementById('ocr-results-container').style.display = 'none';
            document.getElementById('btn-retake-ocr').style.display = 'none';
            document.getElementById('btn-next-step2').disabled = true;

            const snapImg = document.getElementById('camera-snapshot-img');
            if (snapImg) snapImg.style.display = 'none';

            document.getElementById('file-input').value = '';
            appState.completedSteps.delete(2);
            updateStepUI();

            showToast('Foto & Hasil OCR dibersihkan.', 'info');
        }

        // ─── Langkah 3: Real-Time GPS Telemetry ───
        async function fetchGPSStatus() {
            try {
                const res = await fetch('/current-status');
                const data = await res.json();
                const dot = document.getElementById('gps-status-dot');
                const txt = document.getElementById('gps-status-text');

                if (data.connected || data.simulation) {
                    dot.className = 'status-dot';
                    txt.textContent = data.simulation ? 'GPS Simulation Mode' : 'GPS Connected (Live)';
                } else {
                    dot.className = 'status-dot offline';
                    txt.textContent = 'GPS Receiver Disconnected';
                }
            } catch (e) {
                // Ignore silent fetch errors
            }
        }

        async function fetchLiveLocation() {
            try {
                const res = await fetch('/live-location');
                if (!res.ok) return;
                const data = await res.json();

                if (data.latitude !== null && data.longitude !== null) {
                    appState.gpsData = data;
                    updateGPSDisplay(data);
                }
            } catch (e) {
                // Ignore silent background errors
            }
        }

        async function refreshGPSData() {
            const icon = document.getElementById('refresh-gps-icon');
            if (icon) icon.classList.add('spinner');

            try {
                const res = await fetch('/check-location');
                const data = await res.json();

                if (data.error) {
                    showToast(data.error, 'warning');
                } else {
                    appState.gpsData = data;
                    updateGPSDisplay(data);
                    appState.completedSteps.add(3);
                    updateStepUI();
                    showToast('Koordinat GPS berhasil diperbarui!', 'success');
                }
            } catch (e) {
                showToast(`Gagal membaca GPS: ${e.message}`, 'danger');
            } finally {
                if (icon) icon.classList.remove('spinner');
            }
        }

        function updateGPSDisplay(data) {
            const lat = data.avg_lat || data.latitude || -6.112607;
            const lon = data.avg_lon || data.longitude || 106.881780;
            const alt = data.avg_alt || data.altitude || 12.5;

            // Compute UTM if missing
            if ((!data.easting || !data.northing) && window.proj4) {
                const utm = proj4("EPSG:4326", "EPSG:32748", [parseFloat(lon), parseFloat(lat)]);
                data.easting = utm[0].toFixed(2);
                data.northing = utm[1].toFixed(2);
                data.utm_zone = "48S";
            }

            const slot = data.detected_slot || 'SLOT H1';
            const rtk = data.avg_rtk_status || data.rtk_status || 'RTK FIX';

            document.getElementById('gps-val-lat').textContent = parseFloat(lat).toFixed(6);
            document.getElementById('gps-val-lon').textContent = parseFloat(lon).toFixed(6);
            document.getElementById('gps-val-alt').textContent = `${parseFloat(alt).toFixed(1)} m`;
            document.getElementById('gps-val-easting').textContent = data.easting ? `${data.easting} m` : '708241.53 m';
            document.getElementById('gps-val-northing').textContent = data.northing ? `${data.northing} m` : '9323986.32 m';
            document.getElementById('gps-val-utmzone').textContent = data.utm_zone || '48S';
            document.getElementById('gps-val-rtk').textContent = rtk;
            document.getElementById('gps-val-slot').textContent = slot;
            document.getElementById('gps-val-time').textContent = data.time_wib || new Date().toLocaleString('id-ID');

            drawDepoGrid();
        }

        async function toggleGPSSimulation(enabled) {
            try {
                const res = await fetch('/toggle-simulation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                const data = await res.json();
                showToast(data.message || 'Mode simulasi diperbarui.', 'info');
                fetchGPSStatus();
                refreshGPSData();
            } catch (e) {
                showToast(`Gagal mengubah mode simulasi: ${e.message}`, 'danger');
            }
        }

        // ─── Langkah 4: Summary & Save Record ───
        function renderSummaryCard() {
            document.getElementById('summary-details-container').style.display = 'block';
            document.getElementById('save-success-box').style.display = 'none';

            const size = appState.selectedSize || '20ft';
            const ocr = appState.ocrData || {};
            const gps = appState.gpsData || {};

            document.getElementById('sum-size').textContent = `${size} Container`;
            document.getElementById('sum-no-container').textContent = ocr['Nomor Container :'] || 'N/A';
            document.getElementById('sum-serial-check').textContent = `${ocr['Serial Number :'] || 'N/A'} / ${ocr['Check Number :'] || 'N/A'}`;
            document.getElementById('sum-grade').textContent = ocr['Grade'] || 'Grade : A';

            document.getElementById('sum-slot').textContent = gps.detected_slot || 'SLOT H1';

            const lat = gps.avg_lat || gps.latitude || '-6.112607';
            const lon = gps.avg_lon || gps.longitude || '106.881780';
            document.getElementById('sum-latlon').textContent = `${parseFloat(lat).toFixed(6)}, ${parseFloat(lon).toFixed(6)}`;

            const easting = gps.easting || '708241.53';
            const northing = gps.northing || '9323986.32';
            document.getElementById('sum-utm').textContent = `${easting}E / ${northing}N (${gps.utm_zone || '48S'})`;

            document.getElementById('sum-time').textContent = gps.time_wib || new Date().toLocaleString('id-ID');
        }

        async function submitSaveData(autoResetToStep1 = false) {
            const btnSave = document.getElementById('btn-save-data');
            btnSave.disabled = true;
            btnSave.innerHTML = '<i class="fa-solid fa-spinner spinner"></i> Menyimpan...';

            const payload = {
                tipe_container: appState.selectedSize,
                ocr_data: appState.ocrData || {},
                gps_data: appState.gpsData || {},
                lokasi: (appState.gpsData && appState.gpsData.detected_slot) ? appState.gpsData.detected_slot : 'SLOT H1',
                image_uri: appState.rawImageUri || appState.ocrImageUri || ''
            };

            try {
                const res = await fetch('/send-to-database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                if (data.success) {
                    showToast('Data kontainer berhasil disimpan ke database!', 'success');
                    appState.isFinished = true;
                    appState.completedSteps.add(4);
                    appState.completedSteps.add(5);

                    // Directly load history and transition to Step 5 (Riwayat)
                    await loadHistoryLogs();
                    goToStep(5);
                } else {
                    showToast(`Gagal menyimpan data: ${data.error}`, 'danger');
                }
            } catch (e) {
                showToast(`Terjadi kesalahan koneksi: ${e.message}`, 'danger');
            } finally {
                btnSave.disabled = false;
                btnSave.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Simpan Data Ke Database';
            }
        }

        // ─── Langkah 5: History Log & Export ───
        async function loadHistoryLogs() {
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                if (data.success) {
                    appState.historyLogs = data.history || [];
                    renderHistoryTable();
                }
            } catch (e) {
                console.error('Failed to load history:', e);
            }
        }

        let historyCurrentPage = 1;
        const historyRowsPerPage = 10;

        function renderHistoryTable(resetPage = false) {
            if (resetPage) historyCurrentPage = 1;

            const tbody = document.getElementById('history-table-body');
            const searchQuery = (document.getElementById('history-search').value || '').toLowerCase();
            const filterTanggal = document.getElementById('filter-tanggal').value;
            const filterUkuran = document.getElementById('filter-ukuran').value;
            const filterGrade = document.getElementById('filter-grade').value;

            // Pre-calculate grade based on serial 2 terdepan for filtering and display
            appState.historyLogs.forEach(item => {
                let gradeStr = 'B'; // default
                if (item.serial_number && item.serial_number.length >= 2) {
                    const firstTwo = parseInt(item.serial_number.substring(0, 2), 10);
                    if (!isNaN(firstTwo) && firstTwo >= 30) {
                        gradeStr = 'A';
                    }
                }
                item._calculatedGrade = gradeStr;
            });

            const filtered = appState.historyLogs.filter(item => {
                const noStr = (item.nomor_container || '').toLowerCase();
                const slotStr = (item.lokasi_slot || '').toLowerCase();
                const dateStr = (item.waktu || '').toLowerCase();
                const sizeStr = (item.tipe_container || '').toLowerCase();

                const searchMatch = noStr.includes(searchQuery) ||
                    slotStr.includes(searchQuery) ||
                    dateStr.includes(searchQuery) ||
                    sizeStr.includes(searchQuery);

                let dateMatch = true;
                if (filterTanggal) {
                    dateMatch = dateStr.includes(filterTanggal);
                }

                let sizeMatch = true;
                if (filterUkuran) {
                    sizeMatch = sizeStr === filterUkuran.toLowerCase();
                }

                let gradeMatch = true;
                if (filterGrade) {
                    gradeMatch = item._calculatedGrade === filterGrade;
                }

                return searchMatch && dateMatch && sizeMatch && gradeMatch;
            });

            const totalPages = Math.ceil(filtered.length / historyRowsPerPage) || 1;
            if (historyCurrentPage > totalPages) historyCurrentPage = totalPages;

            const startIndex = (historyCurrentPage - 1) * historyRowsPerPage;
            const paginated = filtered.slice(startIndex, startIndex + historyRowsPerPage);

            const selectAllCb = document.getElementById('select-all-history');
            if (selectAllCb) selectAllCb.checked = false;
            updateDeleteSelectedBtn();

            if (paginated.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="empty-history">
                            <i class="fa-solid fa-box-open" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
                            <p>Belum ada riwayat data tersimpan.</p>
                        </td>
                    </tr>
                `;
                renderHistoryPagination(1, 1);
                return;
            }

            tbody.innerHTML = paginated.map(item => {
                const parts = (item.waktu || '').split(' ');
                const tanggal = parts[0] || '-';
                const jam = parts[1] ? (parts[1] + (parts[2] ? ' ' + parts[2] : '')) : '-';

                return `
                <tr>
                    <td style="text-align: center;">
                        <input type="checkbox" class="history-checkbox" value="${item.id}" onchange="updateDeleteSelectedBtn()">
                    </td>
                    <td style="font-size: 0.8rem; color: var(--text-muted);">${tanggal}</td>
                    <td style="font-size: 0.8rem; color: var(--text-muted);">${jam}</td>
                    <td style="text-align: center;">
                        ${item.image_uri ? `<img src="${item.image_uri}" style="height: 50px; border-radius: 4px; object-fit: cover; border: 1px solid var(--border-color); cursor: pointer; transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.1)'" onmouseout="this.style.transform='scale(1)'" onclick="openImageModal('${item.image_uri}')" alt="Raw Image" title="Klik untuk memperbesar">` : '-'}
                    </td>
                    <td><span class="size-badge" style="position:static;">${item.tipe_container || '20ft'}</span></td>
                    <td style="font-weight: 700; font-family: monospace; color: var(--primary);">
                        ${item.nomor_container || 'N/A'}
                        <div style="font-size: 0.7rem; color: var(--text-dim); margin-top: 4px;">
                            Grade: <span class="grade-badge ${item._calculatedGrade.toLowerCase()}" style="padding: 0.15rem 0.4rem; font-size: 0.65rem; border-radius: 4px;">Grade ${item._calculatedGrade}</span>
                        </div>
                    </td>
                    <td style="font-weight: 700; color: var(--success);">${item.lokasi_slot || 'N/A'}</td>
                    <td style="text-align: center;">
                        <button class="btn btn-danger" style="padding: 0.25rem 0.55rem; font-size: 0.75rem; border-radius: 6px;" onclick="deleteSingleRecord(${item.id})" title="Hapus Item Ini">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `}).join('');

            renderHistoryPagination(historyCurrentPage, totalPages);
        }

        function renderHistoryPagination(current, total) {
            const container = document.getElementById('history-pagination-controls');
            container.innerHTML = `
                <button class="btn btn-secondary" style="padding: 0.4rem 0.8rem;" ${current === 1 ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : ''} onclick="historyCurrentPage--; renderHistoryTable()">Sebelumnya</button>
                <span style="font-size:0.9rem; font-weight:600; color:var(--text-main);">Halaman ${current} dari ${total}</span>
                <button class="btn btn-secondary" style="padding: 0.4rem 0.8rem;" ${current === total ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : ''} onclick="historyCurrentPage++; renderHistoryTable()">Selanjutnya</button>
            `;
        }

        function toggleSelectAllHistory(checked) {
            const checkboxes = document.querySelectorAll('.history-checkbox');
            checkboxes.forEach(cb => cb.checked = checked);
            updateDeleteSelectedBtn();
        }

        function updateDeleteSelectedBtn() {
            const selected = document.querySelectorAll('.history-checkbox:checked');
            const btn = document.getElementById('btn-delete-selected');
            const selectAllCb = document.getElementById('select-all-history');
            const allCb = document.querySelectorAll('.history-checkbox');

            if (btn) {
                btn.disabled = selected.length === 0;
                btn.innerHTML = `<i class="fa-solid fa-trash-can"></i> Hapus Terpilih ${selected.length > 0 ? `(${selected.length})` : ''}`;
            }
            if (selectAllCb && allCb.length > 0) {
                selectAllCb.checked = selected.length === allCb.length;
            }
        }

        async function deleteSingleRecord(id) {
            if (!confirm('Apakah Anda yakin ingin menghapus 1 record data ini dari riwayat?')) return;
            try {
                const res = await fetch(`/api/history/${id}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    showToast('Record data berhasil dihapus.', 'info');
                    loadHistoryLogs();
                }
            } catch (e) {
                showToast(`Gagal menghapus record: ${e.message}`, 'danger');
            }
        }

        async function deleteSelectedRecords() {
            const checkboxes = document.querySelectorAll('.history-checkbox:checked');
            const ids = Array.from(checkboxes).map(cb => cb.value);
            if (ids.length === 0) return;

            if (!confirm(`Apakah Anda yakin ingin menghapus ${ids.length} record data terpilih?`)) return;

            try {
                const res = await fetch('/api/history/delete-selected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message || `${ids.length} record berhasil dihapus.`, 'info');
                    loadHistoryLogs();
                }
            } catch (e) {
                showToast(`Gagal menghapus record terpilih: ${e.message}`, 'danger');
            }
        }

        async function clearHistoryLog() {
            if (!confirm('Apakah Anda yakin ingin menghapus SELURUH data riwayat? Action ini tidak dapat dibatalkan.')) return;
            try {
                const res = await fetch('/api/history', { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    showToast('Seluruh riwayat berhasil dibersihkan.', 'info');
                    loadHistoryLogs();
                }
            } catch (e) {
                showToast(`Gagal menghapus riwayat: ${e.message}`, 'danger');
            }
        }

        function resetWorkflowNewInput() {
            appState.isFinished = false;
            appState.selectedSize = null;
            appState.ocrData = null;
            appState.ocrImageUri = null;
            appState.completedSteps.clear();

            document.getElementById('size-card-20ft').classList.remove('selected');
            document.getElementById('size-card-40ft').classList.remove('selected');
            document.getElementById('btn-next-step1').disabled = true;

            resetStep2Data();
            goToStep(1);
            showToast('Alur program di-reset. Siap untuk input data baru!', 'info');
        }

        // ─── Utility Toast Notifications ───
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast';

            const iconMap = {
                info: 'fa-circle-info',
                success: 'fa-circle-check',
                warning: 'fa-triangle-exclamation',
                danger: 'fa-circle-xmark'
            };

            const colorMap = {
                info: 'var(--success)',
                success: 'var(--success)',
                warning: 'var(--warning)',
                danger: 'var(--danger)'
            };

            toast.innerHTML = `
                <i class="fa-solid ${iconMap[type] || 'fa-circle-info'}" style="color: ${colorMap[type]};"></i>
                <span>${message}</span>
            `;

            container.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(100%)';
                toast.style.transition = 'all 0.3s ease';
                setTimeout(() => toast.remove(), 300);
            }, 3500);
        }
        function openImageModal(src) {
            const modal = document.getElementById('image-modal');
            const modalImg = document.getElementById('modal-img');
            modalImg.src = src;
            modal.style.display = 'flex';
        }

        function closeImageModal() {
            document.getElementById('image-modal').style.display = 'none';
        }

        async function logout() {
            try {
                await fetch('/api/logout', { method: 'POST' });
                window.location.href = '/login';
            } catch (e) {
                console.error(e);
            }
        }
    