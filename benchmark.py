import timeit
from PIL import Image, ImageFilter, ImageChops, ImageOps
import cv2
import numpy as np

# Define image paths
image_path1 = 'images/DSC00001.JPG'
image_path2 = image_path1

# Define functions for PIL
def pil_open_image():
    img = Image.open(image_path1)
    return img

def pil_weighted_average(img1, img2):
    return Image.blend(img1, img2, alpha=0.5)

def pil_blur_image(img):
    return img.filter(ImageFilter.BLUR)

def pil_merge_images(img1, img2):
    return ImageChops.add(img1, img2)

def pil_resize_image(img):
    return img.resize((100, 100))

def pil_rotate_image(img):
    return img.rotate(45)

def pil_convert_to_grayscale(img):
    return ImageOps.grayscale(img)

def pil_edge_detection(img):
    return img.filter(ImageFilter.FIND_EDGES)

# Define functions for OpenCV
def cv_open_image():
    img = cv2.imread(image_path1)
    return img

def cv_weighted_average(img1, img2):
    return cv2.addWeighted(img1, 0.5, img2, 0.5, 0)

def cv_blur_image(img):
    return cv2.GaussianBlur(img, (5, 5), 0)

def cv_merge_images(img1, img2):
    return cv2.add(img1, img2)

def cv_resize_image(img):
    return cv2.resize(img, (100, 100))

def cv_rotate_image(img):
    (h, w) = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, 45, 1.0)
    return cv2.warpAffine(img, M, (w, h))

def cv_convert_to_grayscale(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

def cv_edge_detection(img):
    return cv2.Canny(img, 100, 200)

# Conversion functions
def cv2_to_pil(cv2_img):
    '''Convert OpenCV image (numpy.ndarray) to PIL Image.'''
    cv2_img_rgb = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(cv2_img_rgb)
    return pil_img

def pil_to_cv2(pil_img):
    '''Convert PIL Image to OpenCV image (numpy.ndarray).'''
    cv2_img = np.array(pil_img)
    cv2_img = cv2.cvtColor(cv2_img, cv2.COLOR_RGB2BGR)
    return cv2_img

# Load images for PIL
pil_img1 = pil_open_image()
pil_img2 = Image.open(image_path2)

# Load images for OpenCV
cv_img1 = cv_open_image()
cv_img2 = cv2.imread(image_path2)

# Complex conversion and processing functions
def pil_to_cv2_processing():
    pil_img = pil_open_image()
    cv_img = pil_to_cv2(pil_img)
    cv_img = cv_blur_image(cv_img)
    cv_img = cv_rotate_image(cv_img)
    cv_img = cv_edge_detection(cv_img)
    return cv_img

def cv2_to_cv2_processing():
    cv_img = cv_open_image()
    cv_img = pil_to_cv2(cv_img)
    cv_img = cv_blur_image(cv_img)
    cv_img = cv_rotate_image(cv_img)
    cv_img = cv_edge_detection(cv_img)
    return cv_img

def cv2_to_pil_processing():
    cv_img = cv_open_image()
    pil_img = cv2_to_pil(cv_img)
    pil_img = pil_blur_image(pil_img)
    pil_img = pil_rotate_image(pil_img)
    pil_img = pil_edge_detection(pil_img)
    return pil_img

def cv2_via_pil_processing():
    pil_img = pil_open_image()
    return pil_to_cv2(pil_img)

# Benchmarking
tasks = [
    # ('Open Image', pil_open_image, cv_open_image),
    # ('Weighted Average', lambda: pil_weighted_average(pil_img1, pil_img2), lambda: cv_weighted_average(cv_img1, cv_img2)),
    # ('Blur Image', lambda: pil_blur_image(pil_img1), lambda: cv_blur_image(cv_img1)),
    # ('Merge Images', lambda: pil_merge_images(pil_img1, pil_img2), lambda: cv_merge_images(cv_img1, cv_img2)),
    # ('Resize Image', lambda: pil_resize_image(pil_img1), lambda: cv_resize_image(cv_img1)),
    # ('Rotate Image', lambda: pil_rotate_image(pil_img1), lambda: cv_rotate_image(cv_img1)),
    # ('Convert to Grayscale', lambda: pil_convert_to_grayscale(pil_img1), lambda: cv_convert_to_grayscale(cv_img1)),
    # ('Edge Detection', lambda: pil_edge_detection(pil_img1), lambda: cv_edge_detection(cv_img1)),
    # ('Convert OpenCV to PIL', lambda: cv2_to_pil(cv_img1), lambda: cv2_to_pil(cv_img1)),
    # ('Convert PIL to OpenCV', lambda: pil_to_cv2(pil_img1), lambda: pil_to_cv2(pil_img1)),
    # ('PIL to OpenCV Processing', pil_to_cv2_processing, pil_to_cv2_processing),
    # ('OpenCV to PIL Processing', cv2_to_pil_processing, cv2_to_pil_processing),
    # ('OpenCV to OpenCV Processing', cv2_to_cv2_processing, cv2_to_cv2_processing),
    ('OpenCV vs PIL2CV', cv2_via_pil_processing, cv_open_image),
    
    
]

for task_name, pil_task, cv_task in tasks:
    pil_time = timeit.timeit(pil_task, number=10)
    cv_time = timeit.timeit(cv_task, number=10)
    print(f'{task_name} - PIL: {pil_time:.6f}s, OpenCV: {cv_time:.6f}s')
