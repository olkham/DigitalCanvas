import unittest
from PIL import Image
from utils import *

class TestUtils(unittest.TestCase):

    def test_check_and_create(self):
        dirpath = "/path/to/test/directory"
        check_and_create(dirpath)
        self.assertTrue(os.path.exists(dirpath))

    def test_create_thumbnail(self):
        image_path = "/path/to/test/image.jpg"
        thumbnail_path = "/path/to/test/thumbnail.jpg"
        create_thumbnail(image_path, thumbnail_path)
        self.assertTrue(os.path.exists(thumbnail_path))

    def test_replace_webp_extension(self):
        filename = "image.jpg.webp"
        new_filename = replace_webp_extension(filename)
        self.assertEqual(new_filename, "image.jpg")

    def test_save_remote_image(self):
        image_url = "https://example.com/image.jpg"
        upload_folder = "/path/to/test/upload"
        save_remote_image(image_url, upload_folder)
        self.assertTrue(os.path.exists(upload_folder + "/image.jpg"))

    def test_create_thumbnails_for_existing_images(self):
        images = ["/path/to/test/image1.jpg", "/path/to/test/image2.jpg"]
        thumbs = ["/path/to/test/thumb1.jpg", "/path/to/test/thumb2.jpg"]
        create_thumbnails_for_existing_images(images, thumbs)
        self.assertTrue(os.path.exists(thumbs[0]))
        self.assertTrue(os.path.exists(thumbs[1]))

    def test_is_raspberry_pi(self):
        self.assertFalse(is_raspberry_pi())  # Assuming the test environment is not a Raspberry Pi

    def test_get_system_uuid(self):
        system_uuid = get_system_uuid()
        self.assertIsInstance(system_uuid, str)

    def test_get_short_system_uuid(self):
        short_system_uuid = get_short_system_uuid()
        self.assertIsInstance(short_system_uuid, str)

    def test_is_portrait(self):
        image_path = "/path/to/test/image.jpg"
        self.assertFalse(is_portrait(image_path))  # Assuming the test image is not a portrait

    def test_is_landscape(self):
        image_path = "/path/to/test/image.jpg"
        self.assertTrue(is_landscape(image_path))  # Assuming the test image is a landscape

    def test_resize_image(self):
        image = Image.open("/path/to/test/image.jpg")
        screen_width = 1920
        screen_height = 1080
        orientation = "landscape"
        rotation = 0
        resized_image = resize_image(image, screen_width, screen_height, orientation, rotation)
        self.assertIsInstance(resized_image, Image.Image)

    def test_resize_to_fill(self):
        image_width = 1000
        image_height = 800
        screen_width = 1920
        screen_height = 1080
        resized_width, resized_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
        self.assertEqual(resized_width, 1920)
        self.assertEqual(resized_height, 1080)

    def test_resize_to_fit_height(self):
        image_width = 1000
        image_height = 800
        screen_height = 1080
        resized_width, resized_height = resize_to_fit_height(image_width, image_height, screen_height)
        self.assertEqual(resized_width, 1350)
        self.assertEqual(resized_height, 1080)

    def test_resize_to_fit_width(self):
        image_width = 1000
        image_height = 800
        screen_width = 1920
        resized_width, resized_height = resize_to_fit_width(image_width, image_height, screen_width)
        self.assertEqual(resized_width, 1920)
        self.assertEqual(resized_height, 1536)

    def test_crop_center(self):
        image = Image.open("/path/to/test/image.jpg")
        size = (800, 600)
        cropped_image = crop_center(image, size)
        self.assertIsInstance(cropped_image, Image.Image)

    def test_resize_to_target(self):
        src_image = Image.open("/path/to/test/src_image.jpg")
        target_image = "/path/to/test/target_image.jpg"
        resize_option = "fill"
        resize_to_target(src_image, target_image, resize_option)
        self.assertTrue(os.path.exists(target_image))

    def test_read_image_from_url(self):
        image_url = "https://example.com/image.jpg"
        image = read_image_from_url(image_url)
        self.assertIsInstance(image, Image.Image)

    def test_get_thumbnail(self):
        json_data = {"image_path": "/path/to/test/image.jpg", "size": (200, 200)}
        thumbnail = get_thumbnail(json_data)
        self.assertIsInstance(thumbnail, Image.Image)

    def test_strtobool(self):
        self.assertTrue(strtobool("True"))
        self.assertFalse(strtobool("False"))

    def test_accel_to_orientation(self):
        accel = (0.1, 0.2, 0.9)
        orientation = accel_to_orientation(accel)
        self.assertIsInstance(orientation, str)

    def test_luminance_to_brightness(self):
        luminance = 0.5
        brightness = luminance_to_brightness(luminance)
        self.assertIsInstance(brightness, float)

    def test_check_os(self):
        self.assertIsInstance(check_os(), str)

    def test_check_admin_privileges(self):
        self.assertIsInstance(check_admin_privileges(), bool)

if __name__ == '__main__':
    unittest.main()