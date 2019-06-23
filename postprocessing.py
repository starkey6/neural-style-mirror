# -*- coding: utf-8 -*-
from __future__ import print_function, division, absolute_import

import argparse
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageEnhance
from qtpy.QtCore import QBuffer, QIODevice


def normalize(img):
    h, w = img.shape
    x = np.floor(img % w)
    y = np.floor(img / w)
    cx = np.abs(x - w / 2)
    cy = np.abs(y - h / 2)
    energy = (cx**0.5 + cy**0.5)
    return np.maximum(energy * energy, 0.01)


def ellipse(w, h):
    offset = (w + h) / 2. / (w * h)
    y, x = np.ogrid[-h:h + 1., -w:w + 1.]
    return np.uint8((x / w)**2 + (y / h)**2 - offset <= 1)


def fftfilter(img, threshold=92, radius=6, middle=4):
    img = np.float32(img)[:, :, :3].transpose(2, 0, 1)

    rows, cols = img.shape[-2:]
    coefs = normalize(np.arange(rows * cols).reshape(rows, cols))

    fft = np.empty((3, rows, cols, 2))
    mid = middle * 2
    rad = radius
    ew, eh = cols // mid, rows // mid
    pw, ph = (cols - ew * 2) // 2, (rows - eh * 2) // 2
    middle = np.pad(ellipse(ew, eh), ((ph, rows - ph - eh * 2 - 1), (pw, cols - pw - ew * 2 - 1)), 'constant')

    for i in range(3):
        fft[i] = cv2.dft(img[i], flags=18)
        fft[i] = np.fft.fftshift(fft[i])
        spectrum = 20 * np.log(cv2.magnitude(fft[i, :, :, 0], fft[i, :, :, 1]) * coefs)

        ret, thresh = cv2.threshold(np.float32(np.maximum(0, spectrum)), threshold, 255, cv2.THRESH_BINARY)
        thresh *= 1 - middle
        thresh = cv2.dilate(thresh, ellipse(rad, rad))
        thresh = cv2.GaussianBlur(thresh, (0, 0), rad / 3., 0, 0, cv2.BORDER_REPLICATE)
        thresh = 1 - thresh / 255

        img_back = fft[i] * np.repeat(thresh[..., None], 2, axis=2)
        img_back = np.fft.ifftshift(img_back)
        img_back = cv2.idft(img_back)
        img[i] = cv2.magnitude(img_back[:, :, 0], img_back[:, :, 1])

    return Image.fromarray(np.uint8(np.clip(img.transpose(1, 2, 0), 0, 255)))


def qt_to_pil_image(qimg):
    buffer = QBuffer()
    buffer.open(QIODevice.ReadWrite)
    # preserve alha channel with png
    # otherwise ppm is more friendly with Image.open
    if qimg.hasAlphaChannel():
        qimg.save(buffer, 'png')
    else:
        qimg.save(buffer, 'ppm')

    b = BytesIO()
    try:
        b.write(buffer.data())
    except TypeError:
        # the types seemed to change between versions of qtpy
        b.write(buffer.data().data())
    buffer.close()
    b.seek(0)

    pil_img = Image.open(b)
    return pil_img


def resize_axis(img, length=1024):
    longest = max(img.width, img.height)
    ratio = length / (1. * longest)
    resolution = (int(img.width * ratio), int(img.height * ratio))

    return img.resize(resolution, Image.BICUBIC)


def postprocess(img, length=1024, fft=True, threshold=92, radius=6, middle=4, contrast=1.05):
    if fft:
        img = fftfilter(img, threshold=threshold, radius=radius, middle=middle)
    if length > 0:
        img = resize_axis(img, length)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    return img


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='An fft-based descreen filter')
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--nofft', action="store_true", help='Do not apply FFT filter')
    parser.add_argument(
        '--thresh', '-t', default=92, type=int, help='Threshold level for normalized magnitude spectrum')
    parser.add_argument('--radius', '-r', default=6, type=int, help='Radius to expand the area of mask pixels')
    parser.add_argument('--middle', '-m', default=4, type=int, help='Ratio for middle preservation')
    parser.add_argument('--contrast', '-c', default=1.05, type=float, help='Contrast adjustment (1.0 for none)')
    parser.add_argument('--length', '-l', default=1024, type=int, help='Output length of image (<= 0 for no resize)')
    args = parser.parse_args()

    img = Image.open(args.input)
    img = postprocess(
        img,
        length=args.length,
        fft=(not args.nofft),
        threshold=args.thresh,
        radius=args.radius,
        middle=args.middle,
        contrast=args.contrast,
    )
    img.save(args.output)
