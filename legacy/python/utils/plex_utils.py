"""Plex media server utilities."""


def get_thumbnail(json_data):
    """Extract thumbnail URL from Plex webhook payload."""
    metadata = json_data.get('Metadata', {})
    library_section_type = metadata.get('librarySectionType')
    
    if library_section_type == 'movie':
        thumb_url = metadata.get('thumb')
    elif library_section_type == 'show':
        thumb_url = metadata.get('grandparentThumb')
    else:
        thumb_url = metadata.get('parentThumb')
        
    return None if thumb_url == 'null' else thumb_url


def get_title(json_data):
    """Extract title from Plex webhook payload."""
    metadata = json_data.get('Metadata', {})
    library_section_type = metadata.get('librarySectionType')
    
    if library_section_type == 'movie':
        title = metadata.get('title')
    elif library_section_type == 'show':
        title = metadata.get('grandparentTitle')
    else:
        title = metadata.get('parentTitle')
        
    return title
