#!/usr/bin/env python
from flask import Flask, render_template, Response
import picamera
from replayCircularIO import BoundedPiCameraCircularIO
from base_camera import BaseCamera
import requests
import time
import xml.etree.ElementTree as ET
import datetime
import queue
import collections
import os
import threading
import logging
import subprocess

qCmd = queue.Queue()
qResp = queue.Queue()
ReplayData = collections.namedtuple('ReplayData', ['CMD', 'DATA'])
fps=30

def replay_response_thread(qCmd,qResp,ReplayData):
    s = requests.Session()
    replayURL=''
    while True:
        try:
            print('Request')
            r = s.post('https://derby.speckfamily.org/derbynet/action.php', data = {'action':'replay-message',
                                                                                  'status':'1',
                                                                                   'finished-replay':'0',
                                                                                   'replay-url':replayURL
                                                                                  }, timeout=5.0)
            xml=ET.fromstring(r.content)
            for c in xml.getchildren():
                if c.tag == 'replay-message':
                    parts = c.text.split(' ')
                    print(parts)
                    if parts[0]=='START':
                        recName='{0}-{1}.h264'.format(parts[1],datetime.datetime.now().strftime("%y%m%d_%H%M%S"))
                        qCmd.put(ReplayData('START',recName))
                    elif parts[0]=='REPLAY':
                        skipBack=float(parts[1])
                        qCmd.put(ReplayData('REPLAY',skipBack))
        except:
            pass
        try:
            resp=qResp.get(timeout=0.1)
            if resp.CMD=='REPLAY-URL':
                replayURL=resp.DATA
                print(replayURL)
        except queue.Empty:
            pass
def camera_thread(qCmd,qResp,ReplayData,camera):
    print('Camera Thread Started')
    stream = BoundedPiCameraCircularIO(camera, seconds=10)
    camera.start_recording(stream, format='h264', intra_period=1)
    time.sleep(2) #wait for camera to warm up
    fName='test.h264' #Initial file
    print('Camera Loop Started')
    try:
        while True:
            #print('Camera Loop')
            camera.wait_recording(0)
            try:
                cmd=qCmd.get(timeout=1.0)
                print('CMD: {0}, {1}'.format(cmd.CMD,cmd.DATA))
                if cmd.CMD == 'START':
                    fName=cmd.DATA
                elif cmd.CMD=='REPLAY':
                    # Keep recording for 2 seconds and only then write the
                    # stream to disk
                    now = camera.timestamp
                    tsStart = now-1e6*float(cmd.DATA)
                    postTriggerSec=1.0
                    tsEnd = now+1e6*postTriggerSec
                    print('start timestamp: {0}'.format(tsStart))
                    print('end timestamp: {0}'.format(tsEnd))
                    camera.wait_recording(1.5)
                    fName=os.path.join('/videos/',fName)
                    first,last = stream.copy_to_bounded(fName,tsStart,tsEnd)
                    print('TS: {0}, {1}'.format(first.timestamp,last.timestamp))
                    mp4fName = '{0}.mp4'.format(os.path.splitext(fName)[0])
                    command = "/usr/bin/MP4Box -add '{1}' -fps {0} '{2}'".format(fps,fName,mp4fName)
                    try:
                        output = subprocess.check_output(command, stderr=subprocess.STDOUT,shell=True)
                        os.remove(fName)
                    except subprocess.CalledProcessError as e:
                        print('FAIL:\ncmd:{}\noutput:{}'.format(e.cmd, e.output),flush=True)
                    url='https://finish.speckfamily.org/videos/{0}'.format(os.path.split(mp4fName)[-1])
                    qResp.put(ReplayData('REPLAY-URL',url))
            except queue.Empty:
                pass
    finally:
        camera.stop_recording()

camera = picamera.PiCamera(
            resolution=(640, 480),
            framerate=fps,
            clock_mode='raw'
        )

app = Flask(__name__)



@app.route('/preview')
def index():
    """Video streaming home page."""
    return render_template('index.html')


def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/video_feed')
def video_feed():
    """Video streaming route. Put this in the src attribute of an img tag."""
    return Response(gen(BaseCamera(camera)),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)

ct=threading.Thread(target=camera_thread,kwargs={'qCmd':qCmd,
                                                  'qResp':qResp,
                                                  'ReplayData':ReplayData,
                                                  'camera':camera})
rt=threading.Thread(target=replay_response_thread,kwargs={'qCmd':qCmd,
                                                  'qResp':qResp,
                                                  'ReplayData':ReplayData})
rt.start()
ct.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', threaded=True)
