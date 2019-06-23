# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function

import os
import re
import smtplib
from datetime import datetime
from email.header import Header
from multiprocessing.pool import ThreadPool
from os.path import basename
from tempfile import NamedTemporaryFile

from PIL import Image
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QInputDialog, QMessageBox, QProgressDialog
from six.moves.email_mime_image import MIMEImage
from six.moves.email_mime_multipart import MIMEMultipart
from six.moves.email_mime_text import MIMEText

import postprocessing

IMAGE_RESIZE_WIDTH = 1024
IMAGE_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'emails')

STYLE_LOGOS = {
    # 'Women in Data Science': os.path.join(os.path.dirname(__file__), 'images', 'wid-logo.png')
}
LOGO_PADDING = 20

# don't apply the fft postprocessing for these styles
STYLE_POSTPROCESSING = {
    'Albrecht Duhrer - Rhinoceros': {
        'fft': False
    },
    'Piet Mondrian - Composition': {
        'fft': False
    },
    'Wassily Kandinksky - Transverse Line': {
        'fft': False
    },
}

PRIMARY_SMTP_SERVER = 'mail.csn.internal'
PRIMARY_SMTP_PORT = 25
PRIMARY_EMAIL_SENDER = 'machineintelligence@bah.com'
PRIMARY_EMAIL_PASSWORD = None
PRIMARY_REPLY_TO = None

FALLBACK_SMTP_SERVER = 'smtp.gmail.com'
FALLBACK_SMTP_PORT = 587
FALLBACK_EMAIL_SENDER = 'bahmachineintelligence@gmail.com'
FALLBACK_EMAIL_PASSWORD = ''  # FILL ME IN!
FALLBACK_REPLY_TO = 'machineintelligence@bah.com'

EMAIL_SUBJECT = u'Generative Art from Booz Allen Hamilton\'s Machine Intelligence'
EMAIL_TEMPLATE = u'''
<!DOCTYPE html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Generative Art from Booz Allen Hamilton\'s Machine Intelligence</title>

<style type="text/css">
body {
font-family: sans-serif;
}
</style>
</head>

<body>
<font face="sans-serif"> <!--fallback for no css support-->
<p>
We hope you enjoyed having your image transformed into a work of art by our artificial neural network!
<p>

<p>
<img src="cid:image" width="${width}" height="${height}" >
<p>

<p>
This demo of advanced machine learning algorithms was created by Booz Allen Hamilton’s Machine
Intelligence Crosscut—a team focused on charting the path forward for the firm’s research and
development of exciting new applications of artificial intelligence and machine learning in fields
such as medicine, business, and law.
<p>

<p>
Booz Allen employees can find out more at:
<a href="https://boozallen.sharepoint.com/sites/MachineIntel">https://boozallen.sharepoint.com/sites/MachineIntel</a>,
or, if you are outside of the firm’s firewall:
<a href="http://www.boozallen.com/analytics">http://www.boozallen.com/analytics</a>.
</p>

<p>
Thanks for stopping by at the Booz Allen Hamilton DC Innovation Center!
<p>

<p>
<i>machineintelligence@bah.com</i>
<br/>
<i>The Booz Allen Hamilton Machine Intelligence Team</i>
<p>
</font>
</body>
</html>
'''


def nongui(fun):
    """Decorator running the function in non-gui thread while
    processing the gui events."""

    def wrap(*args, **kwargs):
        pool = ThreadPool(processes=1)
        async_fn = pool.apply_async(fun, args, kwargs)
        while not async_fn.ready():
            async_fn.wait(0.01)
            QApplication.processEvents()
        return async_fn.get()

    return wrap


def _mkdir(path):
    """Tries to create directory in the path or ensures it exists"""
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise


def validate_email(email):
    """Isn't technically completely correct, but 99.9% solution."""
    rg = re.compile(r'(^[a-zA-Z0-9._%+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}$)')
    if rg.match(email):
        return True
    else:
        return False


def validate_emp_id(emp_id):
    rg = re.compile(r'(^\d{6}$)')
    if rg.match(emp_id):
        return True
    else:
        return False


def get_email(email):
    if validate_emp_id(email):
        return email + '@bah.com'
    elif validate_email(email):
        return email
    return None


def paste_logo(img, style_name):
    if style_name not in STYLE_LOGOS:
        return

    logo = Image.open(STYLE_LOGOS[style_name])
    lw, lh = logo.size
    iw, ih = img.size
    # bottom left
    img.paste(logo, (LOGO_PADDING, ih - lh - LOGO_PADDING), logo)


def _save_image(email_address, capture, cache_dir):
    image = capture.image

    _mkdir(cache_dir)
    img_file = NamedTemporaryFile(dir=cache_dir, suffix='.jpg', delete=False)
    img_file.close()

    # postprocessing
    custom_args = STYLE_POSTPROCESSING.get(capture.style_name, {})
    image = postprocessing.qt_to_pil_image(image)
    image = postprocessing.postprocess(image, length=IMAGE_RESIZE_WIDTH, **custom_args)
    paste_logo(image, capture.style_name)
    image.save(img_file.name, 'JPEG', quality=80)
    with open(os.path.join(cache_dir, 'email.log'), 'a') as f:
        f.write('"{}",{},{:%Y-%m-%d %H:%M:%S}\n'.format(email_address, img_file.name, datetime.now()))
    return img_file.name, image.size


def create_message(recipient, image, size, sender, reply_to):
    msg = MIMEMultipart('related')
    msg['from'] = Header(sender, 'utf-8')
    msg['to'] = Header(recipient, 'utf-8')
    msg['subject'] = Header(EMAIL_SUBJECT, 'utf-8')
    if reply_to:
        msg['reply-to'] = Header(reply_to, 'utf-8')

    template = EMAIL_TEMPLATE
    template = template.replace('${width}', str(size[0]))
    template = template.replace('${height}', str(size[1]))

    text = MIMEText(template, 'html', 'utf-8')
    msg.attach(text)

    with open(image, 'rb') as fp:
        img = MIMEImage(fp.read())
    img.add_header('Content-ID', 'image')
    img.add_header('Content-Disposition', 'inline', filename=basename(image))
    msg.attach(img)

    return msg


def _send_mail(send_to, image, size, server, port, username, password, reply_to):
    msg = create_message(send_to, image, size, username, reply_to)

    smtp = smtplib.SMTP(server, port)
    if password:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(username, password)
    smtp.sendmail(username, send_to, msg.as_string())
    smtp.close()


def send_image(email_address, capture, cache_dir='emails'):
    email_address = get_email(email_address)
    if email_address is None:
        raise ValueError('invalid email')

    img_file, size = _save_image(email_address, capture, cache_dir)

    try:
        _send_mail(
            send_to=email_address,
            image=img_file,
            size=size,
            server=PRIMARY_SMTP_SERVER,
            port=PRIMARY_SMTP_PORT,
            username=PRIMARY_EMAIL_SENDER,
            password=PRIMARY_EMAIL_PASSWORD,
            reply_to=PRIMARY_REPLY_TO,
        )
    except Exception:
        print("Primary email failed, trying fallback.")
        _send_mail(
            send_to=email_address,
            image=img_file,
            size=size,
            server=FALLBACK_SMTP_SERVER,
            port=FALLBACK_SMTP_PORT,
            username=FALLBACK_EMAIL_SENDER,
            password=FALLBACK_EMAIL_PASSWORD,
            reply_to=FALLBACK_REPLY_TO,
        )


def handle_capture(window, capture):
    email, ok = QInputDialog.getText(
        window, 'Email', 'Enter your employee ID or email:', flags=Qt.FramelessWindowHint | Qt.Popup)
    while ok and not get_email(email):
        email, ok = QInputDialog.getText(
            window, 'Email', 'Enter a valid employee ID or email:', flags=Qt.FramelessWindowHint | Qt.Popup)

    if ok:
        print('Send email to %s' % email)
        pb = None
        try:
            pb = QProgressDialog("Sending...", "", 0, 0, window, Qt.FramelessWindowHint | Qt.Popup)
            pb.setWindowModality(Qt.WindowModal)
            pb.setRange(0, 0)
            pb.setMinimumDuration(0)
            pb.setCancelButton(None)
            pb.show()

            nongui(send_image)(email, capture, cache_dir=IMAGE_CACHE_DIR)
        except Exception:
            import traceback
            traceback.print_exc()
            msg = QMessageBox(window)
            msg.setIcon(QMessageBox.Critical)
            msg.setText('Error sending email.')
            msg.setWindowFlags(Qt.FramelessWindowHint | Qt.Popup)
            msg.exec_()
        finally:
            if pb:
                pb.close()
