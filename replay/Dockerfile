FROM balenalib/raspberry-pi-python:3.7-stretch-run
RUN apt-get update \
    && apt-get install -y \
           libraspberrypi0 \
           libraspberrypi-bin \
           gpac \
           git \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN export READTHEDOCS=True;pip install -r /app/requirements-pi.txt --no-cache-dir
RUN pip uninstall -y picamera
RUN mkdir /install \
    && cd /install \
    && git clone https://github.com/waveform80/picamera.git \
    && cd /install/picamera \
    && export READTHEDOCS=True;python setup.py install \
    && cd / \
    && rm -r /install
WORKDIR /app
EXPOSE 8000
CMD gunicorn --threads 5 --workers 1 -b 0.0.0.0:8000 --enable-stdio-inheritance --capture-output --timeout 90 --log-level debug app:app
