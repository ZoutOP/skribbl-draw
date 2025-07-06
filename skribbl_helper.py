import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import KDTree
from scipy.ndimage import binary_erosion
from skimage.color import rgb2lab

from PyQt5.QtGui import QImage


COLOUR_X_START = 54
COLOUR_HEIGHT = 23
COLOUR_WIDTH = 23
NUM_COLOURS = 13


OFFSETS = [np.array([0, 1]), np.array([1, 0]), np.array([0, -1]), np.array([-1, 0])]


def get_colours(img: np.ndarray, x_offset, y_offset) -> list:
    """ Get all colours as a list of tuple. """
    colours = []
    for y in range(2):
        for x in range(13):
            x1 = COLOUR_X_START + (x * COLOUR_WIDTH)
            x2 = COLOUR_X_START + ((x + 1) * COLOUR_WIDTH)
            y1 = img.shape[0] - ((y + 1) * COLOUR_HEIGHT)
            y2 = img.shape[0] - (y * COLOUR_HEIGHT)
            pixel_colour = img[y1 + (COLOUR_HEIGHT // 2)][(x1 + (COLOUR_WIDTH // 2))]
            colours.append((pixel_colour, (x1 + x_offset, y1 + y_offset, x2 + x_offset, y2 + y_offset)))
    return colours


def is_light(pixel):
    return np.all(pixel > 220, axis=-1)


def find_canvas(img: np.ndarray, x_offset: int, y_offset: int) -> tuple:
    """ Find canvas coordinates. """
    h, w, _ = img.shape

    top = 0
    bottom = h
    left = 0
    right = w

    # Scan from top
    while top < bottom:
        row = img[top:top+1, :, :]  # shape (1, w, 3)
        light_fraction = np.mean(is_light(row))
        if light_fraction < 0.05:
            top += 1
        else:
            break

    # Scan from bottom
    while bottom > top:
        row = img[bottom-1:bottom, :, :]
        light_fraction = np.mean(is_light(row))
        if light_fraction < 0.05:
            bottom -= 1
        else:
            break

    # Scan from left
    while left < right:
        col = img[:, left:left+1, :]
        light_fraction = np.mean(is_light(col))
        if light_fraction < 0.05:
            left += 1
        else:
            break

    # Scan from right
    while right > left:
        col = img[:, right-1:right, :]
        light_fraction = np.mean(is_light(col))
        if light_fraction < 0.05:
            right -= 1
        else:
            break

    Image.fromarray(img[top:bottom, left:right]).save('C:\\Users\\kevin\\OneDrive\\Documents\\Projects\\skribble\\canvas.jpeg')
    
    return (
        (x_offset + left, y_offset + top, x_offset + right, y_offset + bottom), 
        get_colours(img[top:bottom, left:right], x_offset, y_offset)
    )


def create_palette_image(palette):
    """
    Create a P-mode image that PIL can use for quantization with a custom palette.
    `palette`: list of (R, G, B) tuples (max 256)
    """
    palette_img = Image.new("P", (1, 1))
    
    flat_palette = []
    for color in palette:
        flat_palette.extend(color)
    # Fill to 256 colors
    while len(flat_palette) < 256 * 3:
        flat_palette.extend((0, 0, 0))

    palette_img.putpalette(flat_palette)
    return palette_img


def blocks_to_pil_image(blocks, brush_size, image_size=None, bg_color=(255, 255, 255)) -> Image.Image:
    """
    Convert block list to a PIL Image.
    - blocks: list of (x, y, (r, g, b)) tuples
    - brush_size: size of square block
    - image_size: (width, height) optional, inferred if not given
    """
    if not blocks:
        raise ValueError("Block list is empty")

    # Infer size if not given
    if image_size is None:
        max_x = max(x for x, _, _ in blocks) + brush_size
        max_y = max(y for _, y, _ in blocks) + brush_size
        image_size = (max_x, max_y)

    img = Image.new("RGB", image_size, bg_color)
    draw = ImageDraw.Draw(img)

    for x, y, color in blocks:
        draw.rectangle([x, y, x + brush_size, y + brush_size], fill=color)

    return img


def quantize_rgb_to_palette_lab(image_rgb, palette_rgb):
    # Convert both to Lab
    img_lab = rgb2lab(image_rgb.astype(np.float32) / 255.0)
    palette_lab = rgb2lab(np.array(palette_rgb).astype(np.float32).reshape(-1, 1, 3) / 255.0).reshape(-1, 3)

    # KDTree on Lab palette
    tree = KDTree(palette_lab)
    h, w, _ = image_rgb.shape
    flat_lab = img_lab.reshape(-1, 3)
    _, idxs = tree.query(flat_lab)
    matched_colors = np.array(palette_rgb)[idxs]

    return matched_colors.reshape(h, w, 3).astype(np.uint8)


def remove_alpha(image: Image.Image, background_color=(255, 255, 255)):
    """
    Converts an RGBA image to RGB, compositing on a solid background.
    """
    if image.mode != "RGBA":
        return image.convert("RGB")
    
    background = Image.new("RGB", image.size, background_color)
    background.paste(image, mask=image.split()[3])  # 3 = alpha channel
    return background


def contours_to_polygons(mask: np.ndarray, epsilon_factor=0.01):
    """
    mask: 2D binary array (True/False or 0/1)
    epsilon_factor: fraction of arc length used to simplify polygon

    Returns: list of polygons (each is Nx2 numpy array of x,y points)
    """
    mask_uint8 = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    polygons = []
    for cnt in contours:
        epsilon = epsilon_factor * cv2.arcLength(cnt, closed=True)
        approx = cv2.approxPolyDP(cnt, epsilon, closed=True)
        polygons.append(approx.reshape(-1, 2))  # shape: (N, 2) → (x, y)

    return polygons


def image_to_polygons(image: np.ndarray, alpha: np.ndarray, palette: list[tuple]):
    polygons = []

    for colour in palette:
        if colour[0] > 240 and colour[1] > 240 and colour[2] > 240:
            continue  # Ignore white.
        mask = np.all(image == colour, axis=-1)
        mask[alpha] = False
        if mask.sum() == 0:
            continue
        # Erode the mask: shrinks blobs inward
        eroded = binary_erosion(mask)

        # Edge = mask - eroded
        contour_mask = mask & ~eroded
        polygons.append((colour, contours_to_polygons(contour_mask)))

    return polygons

    canvas = np.zeros_like(image, dtype=np.uint8)
    for i, poly_data in enumerate(polygons):
        colour, polies = poly_data
        for poly in polies:
            cv2.polylines(canvas, [poly], isClosed=True, color=(int(colour[2]), int(colour[1]), int(colour[0])), thickness=1)
    Image.fromarray(canvas).save('C:\\Users\\kevin\\OneDrive\\Documents\\Projects\\skribble\\polygon.png')




def create_brush_strokes(image: np.ndarray, palette: list[tuple], height: int, width: int):
    scale = max(image.shape[0] / height, image.shape[1] / width)
    new_w = int((image.shape[1] / scale))
    new_h = int((image.shape[0] / scale))
    # Convert RGBA to PIL image
    pil = Image.fromarray(image, mode="RGBA")
    # Downscale with high-quality filter
    downscaled = pil.resize((new_w, new_h), Image.Resampling.NEAREST)
    mask = np.array(downscaled)[:, :, 3] == 0
    palette_img = create_palette_image(palette)
    downscaled = remove_alpha(downscaled)
    downscaled = downscaled.convert('RGB').quantize(palette=palette_img, dither=Image.NONE).convert('RGB')

    downscaled.save('C:\\Users\\kevin\\OneDrive\\Documents\\Projects\\skribble\\resize.png')

    return image_to_polygons(np.array(downscaled), mask, palette)


def downscale_and_quantise(image: np.ndarray, brush_size: int, palette: list[tuple], height: int, width: int):

    scale = max(image.shape[0] / height, image.shape[1] / width)
    new_w = int((image.shape[1] / scale)) // brush_size
    new_h = int((image.shape[0] / scale)) // brush_size

    # Convert RGBA to PIL image
    pil = Image.fromarray(image, mode="RGBA")
    # Downscale with high-quality filter
    downscaled = pil.resize((new_w, new_h), Image.Resampling.NEAREST)
    alpha = np.array(downscaled)[:, :, 3]
    palette_img = create_palette_image(palette)
    downscaled = remove_alpha(downscaled)
    downscaled = downscaled.convert('RGB').quantize(palette=palette_img, dither=Image.NONE).convert('RGB')
    img_small = np.array(downscaled)  # shape (H', W', 4)
    downscaled.save('C:\\Users\\kevin\\OneDrive\\Documents\\Projects\\skribble\\resize.png')

    # Split channels
    rgb = img_small[:, :, :3]

    img_lab = rgb2lab(rgb.astype(np.float32) / 255.0)

    visited = alpha == 0
    indices = np.argwhere(visited == False)

    stroke_list = []

    def is_visited(index) -> bool:
        return visited[index[0], index[1]] == True
    
    def get_colour(index) -> tuple:
        return tuple(img_small[index[0], index[1]])
    
    def visit(index, colour):
        # check right first
        for offset in OFFSETS:
            new_index = index + offset
            if new_index[0] < 0 or new_index[1] < 0 or new_index[0] >= img_lab.shape[0] or new_index[1] >= img_lab.shape[1]:
                continue
            if is_visited(new_index):
                continue
            new_colour = get_colour(new_index)
            if new_colour == colour:
                return new_index
        return None

    for index in indices:
        if is_visited(index):
            continue
        colour = get_colour(index)
        points = [index]
        next_index = index
        while next_index is not None:
            if (v_index := visit(next_index, colour)) is not None:
                points.append(v_index)
                visited[v_index[0], v_index[1]] = True
                next_index = v_index
            else:
                next_index = None
        stroke_list.append((colour, np.asarray(points)))

    print(stroke_list)
    print(len(stroke_list))

    return stroke_list


def qimage_to_np_array(qimage) -> np.ndarray:
    qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
    width = qimage.width()
    height = qimage.height()

    ptr = qimage.bits()
    ptr.setsize(qimage.byteCount())

    arr = np.array(ptr, dtype=np.uint8).reshape((height, width, 4))  # RGBA
    return arr[:, :, :]