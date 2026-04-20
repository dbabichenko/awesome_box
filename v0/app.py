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
            created_at TEXT NOT NULL
        )
    ''')
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

@app.route('/save-annotation', methods=['POST'])
def save_annotation():
    data = request.get_json()
    image_filename = data.get('image_filename')
    annotation_data = data.get('annotation_data')  # JSON strokes
    canvas_data_url = data.get('canvas_data_url')  # base64 of annotation layer

    ocr_text = ''
    if canvas_data_url:
        try:
            # Decode the base64 canvas image
            header, b64 = canvas_data_url.split(',', 1)
            img_bytes = base64.b64decode(b64)
            img = Image.open(io.BytesIO(img_bytes)).convert('RGBA')

            # White background for OCR
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            bg = bg.convert('RGB')

            # Run Tesseract with handwriting config
            ocr_text = pytesseract.image_to_string(
                bg,
                config='--psm 6 --oem 1'
            ).strip()
        except Exception as e:
            ocr_text = f'[OCR error: {str(e)}]'

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'INSERT INTO annotations (image_filename, annotation_data, ocr_text, created_at) VALUES (?, ?, ?, ?)',
        (image_filename, json.dumps(annotation_data), ocr_text, datetime.now().isoformat())
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

@app.route('/annotations/<int:ann_id>', methods=['DELETE'])
def delete_annotation(ann_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM annotations WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()
    return jsonify({'deleted': ann_id})

if __name__ == '__main__':
    app.run(debug=True)
