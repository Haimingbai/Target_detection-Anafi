#!/usr/bin/env python

import csv
import cv2
import math
import os
import shlex
import subprocess
import tempfile

import olympe
from olympe.messages.ardrone3.Piloting import TakeOff, Landing
from olympe.messages.ardrone3.Piloting import moveBy
from olympe.messages.ardrone3.PilotingState import FlyingStateChanged
from olympe.messages.ardrone3.PilotingSettings import MaxTilt
from olympe.messages.ardrone3.GPSSettingsState import GPSFixStateChanged

greenLower = (40, 62, 0)
greenUpper = (96, 255, 255)

# NOTE: Line numbers of this example are referenced in the user guide.
# Don't forget to update the user guide after every modification of this example.


class StreamingExample:

    def __init__(self):
        # Create the olympe.Drone object from its IP address
        self.drone = olympe.Drone(
            "10.202.0.1",
            loglevel=3,
        )
        self.tempd = tempfile.mkdtemp(prefix="olympe_streaming_test_")
        print("Olympe streaming example output dir: {}".format(self.tempd))
        self.h264_frame_stats = []
        self.h264_stats_file = open(
            os.path.join(self.tempd, 'h264_stats.csv'), 'w+')
        self.h264_stats_writer = csv.DictWriter(
            self.h264_stats_file, ['fps', 'bitrate'])
        self.h264_stats_writer.writeheader()

    def start(self):
        # Connect the the drone
        self.drone.connection()

        print("Takeoff if necessary...")
        self.drone(
            FlyingStateChanged(state="hovering", _policy="check")
            | FlyingStateChanged(state="flying", _policy="check")
            | (
                GPSFixStateChanged(fixed=1, _timeout=10, _policy="check_wait")
                >> (
                    TakeOff(_no_expect=True)
                    & FlyingStateChanged(
                        state="hovering", _timeout=10, _policy="check_wait")
                )
            )
        ).wait()

        self.drone(moveBy(0,-1.15,-0.5,-3.142)>> FlyingStateChanged(state="hovering",_timeout=10)).wait()

        self.drone(moveBy(2.0,0, 0,0)>> FlyingStateChanged(state="hovering",_timeout=10)).wait()

        # You can record the video stream from the drone if you plan to do some
        # post processing.
        self.drone.set_streaming_output_files(
            h264_data_file=os.path.join(self.tempd, 'h264_data.264'),
            h264_meta_file=os.path.join(self.tempd, 'h264_metadata.json'),
            # Here, we don't record the (huge) raw YUV video stream
            # raw_data_file=os.path.join(self.tempd,'raw_data.bin'),
            # raw_meta_file=os.path.join(self.tempd,'raw_metadata.json'),
        )

        # Setup your callback functions to do some live video processing
        self.drone.set_streaming_callbacks(
            raw_cb=self.yuv_frame_cb,
            h264_cb=self.h264_frame_cb
        )
        # Start video streaming
        self.drone.start_video_streaming()

    def stop(self):
        # Properly stop the video stream and disconnect
        self.drone.stop_video_streaming()
        self.drone.disconnection()
        self.h264_stats_file.close()

    def yuv_frame_cb(self, yuv_frame):
        """
        This function will be called by Olympe for each decoded YUV frame.

            :type yuv_frame: olympe.VideoFrame
        """
        # the VideoFrame.info() dictionary contains some useful informations
        # such as the video resolution
        info = yuv_frame.info()
        height, width = info["yuv"]["height"], info["yuv"]["width"]

        # convert pdraw YUV flag to OpenCV YUV flag
        cv2_cvt_color_flag = {
            olympe.PDRAW_YUV_FORMAT_I420: cv2.COLOR_YUV2BGR_I420,
            olympe.PDRAW_YUV_FORMAT_NV12: cv2.COLOR_YUV2BGR_NV12,
        }[info["yuv"]["format"]]

        # yuv_frame.as_ndarray() is a 2D numpy array with the proper "shape"
        # i.e (3 * height / 2, width) because it's a YUV I420 or NV12 frame

        # Use OpenCV to convert the yuv frame to RGB
        img = cv2.cvtColor(yuv_frame.as_ndarray(), cv2_cvt_color_flag)

        blurred = cv2.GaussianBlur(img, (11, 11), 0)
        hsv = cv2.cvtColor(img,cv2.COLOR_BGR2HSV)

# Threshold the HSV image to get only certain colors
        mask = cv2.inRange(hsv, greenLower, greenUpper)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        mask = cv2.GaussianBlur(mask, (15, 15), 2, 2)
     
        contours, hierarchy  = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

#shape = cv2.drawContours(img, contours, -1, (0,255,0), 3)

        vx=0.0;
        vy=0.0;
        vz=0.0;
        vr=0.0;
        marker_y=0.0;
        marker_x=0.0;
        kp=0.002;
        largest=None;

     
        for cnt in contours:
            approx = cv2.approxPolyDP(cnt,0.01*cv2.arcLength(cnt,True),True)
	#print (len(approx))
            if len(approx)==4:
                print ("square")
                cv2.drawContours(img,[cnt],0,(0,0,255),-1)
            elif len(approx) > 13:
                print ("circle")
                cv2.drawContours(img,[cnt],0,(0,255,255),-1)
                if largest is None or cv2.contourArea(cnt) > cv2.contourArea(largest):
                    if cv2.contourArea(cnt)<1000000:
                        largest = cnt
			

        if largest is not None:
            cv2.drawContours(img, largest, -1, (0,255,0), 3)
            M=cv2.moments(largest)
            marker_y=int(M["m01"]/M["m00"])
            marker_x=int(M["m10"]/M["m00"])	
            vx=0.1
            vy=0.0
            vz=kp*(img.shape[0]/2-marker_y)
            vr=kp*(img.shape[1]/2-marker_x)
            cv2.circle(img,(marker_x,marker_y),2,(0,0,255),-1)


        cv2.circle(img,(int(img.shape[1]/2),int(img.shape[0]/2)),2,(0,0,255),-1)	
  
        cv2.imshow('img',img)

        self.drone(moveBy(vx, vy, -vz, -vr)).wait(10)

        cv2.waitKey(1)

    def h264_frame_cb(self, h264_frame):
        """
        This function will be called by Olympe for each new h264 frame.

            :type yuv_frame: olympe.VideoFrame
        """

        # Get a ctypes pointer and size for this h264 frame
        frame_pointer, frame_size = h264_frame.as_ctypes_pointer()

        # For this example we will just compute some basic video stream stats
        # (bitrate and FPS) but we could choose to resend it over an another
        # interface or to decode it with our preferred hardware decoder..

        # Compute some stats and dump them in a csv file
        info = h264_frame.info()
        frame_ts = info["ntp_raw_timestamp"]
        if not bool(info["h264"]["is_sync"]):
            if len(self.h264_frame_stats) > 0:
                while True:
                    start_ts, _ = self.h264_frame_stats[0]
                    if (start_ts + 1e6) < frame_ts:
                        self.h264_frame_stats.pop(0)
                    else:
                        break
            self.h264_frame_stats.append((frame_ts, frame_size))
            h264_fps = len(self.h264_frame_stats)
            h264_bitrate = (
                8 * sum(map(lambda t: t[1], self.h264_frame_stats)))
            self.h264_stats_writer.writerow(
                {'fps': h264_fps, 'bitrate': h264_bitrate})

    def fly(self):
        # Takeoff, fly, land, ...
        print("Takeoff if necessary...")
        self.drone(
            FlyingStateChanged(state="hovering", _policy="check")
            | FlyingStateChanged(state="flying", _policy="check")
            | (
                GPSFixStateChanged(fixed=1, _timeout=10, _policy="check_wait")
                >> (
                    TakeOff(_no_expect=True)
                    & FlyingStateChanged(
                        state="hovering", _timeout=10, _policy="check_wait")
                )
            )
        ).wait()

        self.drone(moveBy(0,-1.15,-0.5,-3.142)>> FlyingStateChanged(state="hovering",_timeout=10)).wait()

        #self.drone(moveBy(3.0,0,0,0)>> FlyingStateChanged(state="hovering",_timeout=10)).wait()


    def postprocessing(self):
        # Convert the raw .264 file into an .mp4 file
        h264_filepath = os.path.join(self.tempd, 'h264_data.264')
        mp4_filepath = os.path.join(self.tempd, 'h264_data.mp4')
        subprocess.run(
            shlex.split('ffmpeg -i {} -c:v copy {}'.format(
                h264_filepath, mp4_filepath)),
            check=True
        )

        # Replay this MP4 video file using the default video viewer (VLC?)
        # subprocess.run(
        #     shlex.split('xdg-open {}'.format(mp4_filepath)),
        #     check=True
        # )


if __name__ == "__main__":
    streaming_example = StreamingExample()
    streaming_example.start()
    #streaming_example.fly()
    # Start the video stream
    while True:

        cv2.waitKey(1)
    # Perform some live video processing while the drone is flying
    #streaming_example.fly()
    # Stop the video stream
   # streaming_example.stop()
    # Recorded video stream postprocessing
    #streaming_example.postprocessing()
