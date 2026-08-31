import re

def clean_character(char_text):
    char_text = char_text.strip().upper()
    if len(char_text) > 1:
        char_text = re.sub(r'^[1IL]+', '', char_text)
        char_text = re.sub(r'[1IL]+$', '', char_text)
        if not char_text:
            return char_text.strip().upper()
    ocr_corrections = {
        'O': '0', 'D': '0', 'Q': '0',
        'I': '1', 'L': '1',
        'Z': '2',
        'E': '3',
        'A': '4', 'H': '4',
        'S': '5',
        'G': '6', 'b': '6',
        'T': '7',
        'B': '8',
        'P': '9', 'q': '9',
    }

    if len(char_text) == 1 and char_text in ocr_corrections:
        corrected = ocr_corrections[char_text]
        return corrected
    return char_text

boxes = [
    {'text': 'U', 'prob': 0.99, 'cx': 10, 'cy': 10},
    {'text': '2', 'prob': 1.0, 'cx': 10, 'cy': 20},
    {'text': '9', 'prob': 1.0, 'cx': 10, 'cy': 30},
    {'text': '5', 'prob': 1.0, 'cx': 10, 'cy': 40},
    {'text': '1', 'prob': 1.0, 'cx': 10, 'cy': 50},
    {'text': '4', 'prob': 1.0, 'cx': 10, 'cy': 60},
    {'text': '1', 'prob': 1.0, 'cx': 10, 'cy': 70},
    {'text': '5', 'prob': 0.31, 'cx': 10, 'cy': 80},
]
cleaned_chars = []
for b in boxes:
    cleaned = clean_character(b['text'])
    print(f"Cleaned '{b['text']}' -> '{cleaned}'")
    cleaned_chars.append(cleaned)
raw = "".join(cleaned_chars)
digits_only = re.sub(r'[^0-9]', '', raw)
print(f"digits_only: {digits_only}")
if len(digits_only) >= 7:
    last_7 = digits_only[-7:]
else:
    last_7 = digits_only.zfill(7)
print(f"last_7: {last_7}")
serial = last_7[:6]
check = last_7[6] if len(last_7) >= 7 else '?'
print(f"serial: {serial}, check: {check}")
