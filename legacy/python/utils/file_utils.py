"""File system utilities - directory operations, file listing, unique filenames."""

import os
import re
import uuid


def check_and_create(dirpath):
    """Create directory if it doesn't exist."""
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


def check_for_duplicate_files(dir, file):
    """Check for duplicate files and return unique filename if needed."""
    if os.path.exists(os.path.join(dir, file)):
        base, ext = os.path.splitext(file)
        i = 1
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        file = f"{base}_{i}{ext}"
    return file


def list_files(directory, extensions=None, include_paths=False):
    """List files in directory, optionally filtered by extension."""
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    if extensions:
        if isinstance(extensions, str):
            extensions = [extensions]
        extensions = tuple(ext.lower() for ext in extensions)
        files = [f.name for f in os.scandir(directory) if f.is_file() and f.name.lower().endswith(extensions)]
    else:
        files = [f.name for f in os.scandir(directory) if f.is_file()]
        
    if include_paths:
        files = [os.path.join(directory, f) for f in files]

    return files


def generate_unique_filename(directory, extension):
    """Generate a UUID-based unique filename."""
    filename = str(uuid.uuid4()) + extension
    while os.path.exists(os.path.join(directory, filename)):
        filename = str(uuid.uuid4()) + extension
    return filename


def convert_files_to_unique_filenames(directory, extensions=None):
    """Rename files to UUID-based names if not already."""
    files = list_files(directory, extensions)
    for file in files:
        old_filename = os.path.basename(file)
        if not re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', os.path.splitext(old_filename)[0]):
            ext = os.path.splitext(file)[1]
            new_filename = generate_unique_filename(directory, ext)
            os.rename(os.path.join(directory, file), os.path.join(directory, new_filename))


def replace_webp_extension(filename):
    """Replace .webp extension with original or .jpg."""
    match = re.search(r'\.(jpg|jpeg|png|bmp)\.webp$', filename)
    if match:
        original_extension = match.group(1)
        filename = filename.replace(f'.{original_extension}.webp', f'.{original_extension}')
    else:
        if filename.endswith('.webp'):
            filename = filename.replace('.webp', '.jpg')
    return filename
