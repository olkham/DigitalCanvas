from flask import Flask, request, send_from_directory, render_template_string, redirect, url_for
import os
from PIL import Image
import requests
from io import BytesIO

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'images'
app.config['THUMBNAIL_FOLDER'] = 'thumbnails'


if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

if not os.path.exists(app.config['THUMBNAIL_FOLDER']):
    os.makedirs(app.config['THUMBNAIL_FOLDER'])

def create_thumbnail(image_path, thumbnail_path, size=(100, 100)):
    with Image.open(image_path) as img:
        img.thumbnail(size, Image.ANTIALIAS)
        img.save(thumbnail_path)

def save_remote_image(image_url, upload_folder):
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        filename = os.path.basename(image_url)
        file_path = os.path.join(upload_folder, filename)
        img.save(file_path)
        return filename
    except Exception as e:
        print(f"Failed to fetch image: {e}")
        return None

def create_thumbnails_for_existing_images():
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], filename)
        if not os.path.exists(thumbnail_path):
            create_thumbnail(file_path, thumbnail_path)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' in request.files and request.files['file'].filename != '':
            file = request.files['file']
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)
            thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], file.filename)
            create_thumbnail(file_path, thumbnail_path)
        elif 'image_url' in request.form and request.form['image_url'] != '':
            image_url = request.form['image_url']
            filename = save_remote_image(image_url, app.config['UPLOAD_FOLDER'])
            if filename:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], filename)
                create_thumbnail(file_path, thumbnail_path)
        return redirect(url_for('index'))

    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template_string('''
    <html>
        <body>
            <h1>Upload an image</h1>
            <form method="POST" action="/" enctype="multipart/form-data">
                <input type="file" name="file"><br><br>
                <h1>Or provide an image URL</h1>
                <input type="text" name="image_url" placeholder="Enter image URL"><br><br>
                <input type="submit" value="Upload">
            </form>
            <h1>Uploaded Files</h1>
            <table border="1">
                <tr>
                    <th>Thumbnail</th>
                    <th>Filename</th>
                    <th>Actions</th>
                </tr>
                {% for file in files %}
                <tr>
                    <td><img src="{{ url_for('uploaded_thumbnail', filename=file) }}" alt="Thumbnail" style="width:100px; height:auto;"></td>
                    <td><a href="{{ url_for('uploaded_file', filename=file) }}">{{ file }}</a></td>
                    <td>
                        <form method="POST" action="{{ url_for('delete_file', filename=file) }}" style="display:inline;">
                            <button type="submit">Delete</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </body>
    </html>
    ''', files=files)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/thumbnails/<filename>')
def uploaded_thumbnail(filename):
    return send_from_directory(app.config['THUMBNAIL_FOLDER'], filename)

@app.route('/delete/<filename>', methods=['POST'])
def delete_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
    return redirect(url_for('index'))

if __name__ == '__main__':
    create_thumbnails_for_existing_images()
    app.run(host='0.0.0.0', port=7000, debug=True)
