# Utils package - re-exports all functions for backward compatibility
# This allows existing code to continue using: from utils import function_name

from .image_utils import (
    create_thumbnail,
    create_video_thumbnail,
    is_portrait,
    is_landscape,
    is_video_file,
    is_image_file,
    max_usful_size,
    resize_image,
    resize_to_fill,
    resize_to_fit_height,
    resize_to_fit_width,
    crop_center,
    cv2_crop_center,
    quick_read_image,
    cv2_to_pil,
    pil_to_cv2,
    cv2_rotate_image,
    overlay_image,
    overlay_center,
    resize_to_target,
    cv_resize_to_target,
    cv_resize_to_target_size,
    read_image_from_url,
    read_image_properties,
    read_video_properties,
    save_remote_image,
    create_thumbnails_for_existing_images,
)

from .file_utils import (
    check_and_create,
    check_for_duplicate_files,
    list_files,
    generate_unique_filename,
    convert_files_to_unique_filenames,
    replace_webp_extension,
)

from .system_utils import (
    is_raspberry_pi,
    get_system_uuid,
    get_short_system_uuid,
    check_os,
    check_admin_privileges,
)

from .math_utils import (
    clamp,
    lerp,
    get_mean_value,
    get_mean_values,
    rescale_brightness,
    rescale_luminance,
    luminance_to_brightness,
)

from .sensor_utils import (
    accel_to_orientation,
    accel_to_rotation,
)

from .plex_utils import (
    get_thumbnail,
    get_title,
)

from .conversion_utils import (
    strtobool,
)
