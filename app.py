from flask import Flask, request, jsonify, render_template, send_from_directory
import sqlite3
import base64
import os
import re
from datetime import datetime
from PIL import Image
import pytesseract
import io
import json

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = 'annotations.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_filename TEXT NOT NULL,
            annotation_data TEXT,
            ocr_text TEXT,
            typed_notes TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    # Migrate existing databases that don't yet have the typed_notes column
    try:
        c.execute('ALTER TABLE annotations ADD COLUMN typed_notes TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/upload-image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    f = request.files['image']
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{f.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    f.save(filepath)
    return jsonify({'filename': filename})

def ocr_from_data_url(data_url, label):
    """
    Decode a base64 PNG data URL, flatten onto white, run Tesseract,
    and return the stripped text, or an error string prefixed with label.
    """
    try:
        _, b64 = data_url.split(',', 1)
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGBA')
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        text = pytesseract.image_to_string(
            bg.convert('RGB'),
            config='--psm 6 --oem 1'
        ).strip()
        return text
    except Exception as e:
        return f'[{label} OCR error: {e}]'


@app.route('/save-annotation', methods=['POST'])
def save_annotation():
    data = request.get_json()
    image_filename   = data.get('image_filename')
    annotation_data  = data.get('annotation_data')       # JSON strokes drawn on image
    canvas_data_url  = data.get('canvas_data_url')       # annotation layer (drawn on image)
    hw_canvas_data_url = data.get('hw_canvas_data_url')  # handwritten notes canvas
    typed_notes      = data.get('typed_notes', '').strip()

    parts = []   # collects labelled OCR sections

    # 1. OCR the annotation strokes drawn on top of the image
    if canvas_data_url:
        annotation_ocr = ocr_from_data_url(canvas_data_url, 'Annotation')
        if annotation_ocr:
            parts.append(f'[Image annotations]\n{annotation_ocr}')

    # 2. OCR the handwritten notes canvas independently
    if hw_canvas_data_url:
        hw_ocr = ocr_from_data_url(hw_canvas_data_url, 'Handwriting')
        if hw_ocr:
            parts.append(f'[Handwritten notes]\n{hw_ocr}')

    # 3. Append typed notes verbatim (no OCR needed)
    if typed_notes:
        parts.append(f'[Typed notes]\n{typed_notes}')

    ocr_text = '\n\n'.join(parts)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        '''INSERT INTO annotations
           (image_filename, annotation_data, ocr_text, typed_notes, created_at)
           VALUES (?, ?, ?, ?, ?)''',
        (
            image_filename,
            json.dumps(annotation_data),
            ocr_text,
            typed_notes,
            datetime.now().isoformat()
        )
    )
    row_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({'id': row_id, 'ocr_text': ocr_text})

@app.route('/annotations', methods=['GET'])
def get_annotations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM annotations ORDER BY created_at DESC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/annotations/<int:ann_id>', methods=['GET'])
def get_annotation(ann_id):
    """Return a single annotation by ID — used by the QR code scanner."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM annotations WHERE id = ?', (ann_id,))
    row = c.fetchone()
    conn.close()
    if row is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(row))

@app.route('/annotations/<int:ann_id>', methods=['DELETE'])
def delete_annotation(ann_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM annotations WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    return jsonify({'deleted': ann_id})

if __name__ == '__main__':
    # app.run(debug=True)
    app.run(debug=False, host='0.0.0.0', port=80)
