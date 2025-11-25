#!/usr/bin/python3

import hashlib
import json
import logging
import re
import warnings
import functools
import datetime
import subprocess
from datetime import datetime
from enum import Enum

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client


class LedStates(Enum):
    RDY_and_APP_always_off = 0
    RDY_and_APP_automatic_update = 1
    RDY_always_on_APP_always_off = 2
    RDY_always_off_APP_always_on = 3
    RDY_and_APP_always_on = 4


import requests
import sys
import os
import time
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager, HTTPConnectionPool
from zoneinfo import ZoneInfo


try:
    from http.client import HTTPConnection
except ImportError:
    from http.client import HTTPConnection


class MyAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        # save these values for pickling
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block
        self.poolmanager = MyPoolManager(num_pools=connections, maxsize=maxsize,
                                       block=block, strict=True, **pool_kwargs)


class MyPoolManager(PoolManager):
    def _new_pool(self, scheme, host, port, request_context=None):
        return MyHTTPConnectionPool(host, port, **self.connection_pool_kw)


class MyHTTPConnectionPool(HTTPConnectionPool):
    def _new_conn(self):
        self.ConnectionCls = MyHTTPConnection
        self.num_connections += 1

        conn = self.ConnectionCls(
            host=self.host,
            port=self.port,
            timeout=self.timeout.connect_timeout,
            **self.conn_kw
        )
        return conn



class MyHTTPConnection(HTTPConnection):
    def _send_output(self, message_body=None, encode_chunked=False):
        """Send the currently buffered request and clear the buffer.

        Appends an extra \\r\\n to the buffer.
        A message_body may be specified, to be appended to the request.
        """
        self._buffer.extend((b"", b""))
        msg = b"\r\n".join(self._buffer)
        del self._buffer[:]
        # If msg and message_body are sent in a single send() call,
        # it will avoid performance problems caused by the interaction
        # between delayed ack and the Nagle algorithm.
        if isinstance(message_body, bytes):
            msg += message_body
            message_body = None
        self.send(msg)
        if message_body is not None:
            # message_body was not a string (i.e. it is a file), and
            # we must run the risk of Nagle.
            self.send(message_body)


def deprecated(func):
    """This is a decorator which can be used to mark functions as deprecated.
    It will result in a warning being emitted when the function is used."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(
            f"{func.__name__} is deprecated and will be removed in a future version.",
            category=DeprecationWarning,
            stacklevel=2
        )
        return func(*args, **kwargs)

    return wrapper

# class to handle the challenge response connection mechanism via digest access authentication (see comment above)
class ChallengeResponseConnect():
    def __init__(self, p_ip, p_user, p_password, precalc_user_hash=None, debug=False):
        os.environ['NO_PROXY'] = p_ip
        if debug:
            print(sys.version)
            print("requests:" + requests.__version__)

        self.ip = p_ip
        self.user = p_user
        self.password = p_password
        self.precalc_user_hash = precalc_user_hash
        self.debug = debug
        self.get_challenge()

    def get_challenge(self):
        # get challenge from sec100 for digest calculation
        header = {"Content-Type": "application/octet-stream"}
        user = {"data": {"user": self.user}}
        r_challenge = requests.post(
            'http://' + self.ip + '/api/getChallenge/', data=json.dumps(user), headers=header, timeout=10)
        print(f"\t\t\tgetChallenge response: {r_challenge} {r_challenge.reason} {r_challenge.text}")
        self.challenge = r_challenge.json()['challenge']

        self.session = requests.Session()

        # interface offers possibility to pass a precalculated hash for e.g. User SICKService
        # if it is not provided use Username and Password
        if self.precalc_user_hash is None:
            realm = self.challenge["realm"]
            self.ha1 = self.build_digest(self.user, realm, self.password)
        else:
            self.ha1 = self.precalc_user_hash

        # You must initialize logging, otherwise you'll not see debug output.
        if self.debug:
            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True

    # function to calculate the sha256 for the given array of items (e.g.  sha256(username:realm:password) )
    def build_digest(self, *arr):
        hash = hashlib.sha256()
        hash.update(":".join(arr).encode('utf-8'))
        return hash.hexdigest()

    # computes the HA2 and response part for the digest access authentication
    def compute_response_digest(self, method, digest_uri, challenge):
        nonce = challenge["nonce"]

        if challenge['salt'] is None:
            ha1 = self.build_digest(self.user, challenge['realm'], self.password)
            #ha1 = hashlib.sha256(f"{self.user}:{challenge['realm']}:{self.password}".encode()).hexdigest()
        else:
            password_encoded = self.user + ":" + challenge['realm'] + ":" + self.password + ":"
            password_ascii = [ord(e) for e in password_encoded]
            password_salted_hash = hashlib.sha256(bytes(password_ascii + challenge["salt"])).hexdigest()

            ha1 = password_salted_hash

        ha2 = self.build_digest(method, digest_uri)
        return self.build_digest(ha1, nonce, ha2)

    def gen_body_data(self, digest_uri, data, method='POST'):
        body_data = {
            'header': {
                'nonce': self.challenge['nonce'],
                'opaque': self.challenge['opaque'],
                'realm': self.challenge['realm'],
                'response': self.compute_response_digest(method, digest_uri, self.challenge),
                'user': self.user
            }
        }

        if data:
            body_data['data'] = data

        return body_data

    # generate the GET request
    def make_get_request(self, uri, stream=False):

        # allow some retries if the POST request cannot be served immediately
        for loopCnt in range(50):

            ret = self.session.get('http://' + self.ip + uri, stream=stream)
            if ret.status_code == 200 or ret.status_code == 404:
                break
            elif ret.status_code == 400:
                print("400: {} {}".format(uri, loopCnt))

            time.sleep(.25)

        return ret

    # generates the POST request for the given item
    def make_request(self, uri, data=None, timeout=None):

        digest_uri = uri[5:]  # hooray for magic numbers

        body_data = self.gen_body_data(digest_uri, data)

        ret = self.session.post('http://' + self.ip + uri, data=json.dumps(body_data), stream=False, timeout=timeout)
        if self.isAccessDenied(ret) or self.isInvalidChallenge(ret) or ret.status_code == 400:
            print(f"Get new challenge due to accessDenied {self.isAccessDenied(ret)}, invalid Challenge {self.isInvalidChallenge(ret)} status code 400 {ret.status_code == 400}")
            self.get_challenge()
            ret = self.session.post('http://' + self.ip + uri, data=json.dumps(body_data), stream=False)
        return ret

    def upload_file(self, file_path, file_name, chunk_size=65536):

        with open(file_path, 'rb') as file:
            chunk = file.read(chunk_size)
            first_chunk = True
            while chunk:
                if first_chunk:
                    params = {'append': "false", 'finish': "false"}
                    first_chunk = False
                else:
                    params = {'append': "true", 'finish': "false"}

                next_chunk = file.read(chunk_size)
                if not next_chunk:
                    params['finish'] = "true"

                res = self.make_file_upload_request(f"/file/upload/{file_name}", params, chunk)
                #res = sec100.com.session.post(url, data=chunk, params=params)
                res.raise_for_status()
                print(f"Chunk upload status: {res.status_code}")

                chunk = next_chunk
                print(f"Chunk upload status: {res.status_code}")

            # check last status code
            if not self.isValidReply(res):
                print(f"Error {res.json()['header']['status']}: {res.json()['header']['message']}")

        return res

    def make_file_upload_request(self, uri, parameter, data):

        digest_uri = uri[13:]  # hooray for magic numbers

        body_data = self.gen_body_data(digest_uri, None)

        json_data = json.dumps(body_data).encode('utf-8')

        # Append the binary data to the JSON bytes
        combined_data = json_data + data
        ret = self.session.post('http://' + self.ip + uri, params=parameter, data=combined_data, stream=False)
        if self.isAccessDenied(ret) or self.isInvalidChallenge(ret) or ret.status_code == 400:
            print(f"Get new challenge due to accessDenied {self.isAccessDenied(ret)}, invalid Challenge {self.isInvalidChallenge(ret)} status code 400 {ret.status_code == 400}")
            self.get_challenge()
            ret = self.session.post('http://' + self.ip + uri, params=parameter, data=combined_data, stream=False)
        return ret



    def download_file(self, file_name):
        url = f'http://{self.ip}/file/download/{file_name}'
        data = bytearray()

        body_data = self.gen_body_data(file_name, data, method='POST')

        with self.session.post(url, data=json.dumps(body_data), stream=True) as response:
            response.raise_for_status()  # Check for HTTP errors
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # Filter out keep-alive new chunks
                    data.extend(chunk)
        return data

    def isValidReply(self, msg):
        return msg.status_code == 200 and msg.json()['header']['status'] == 0

    def isAccessDenied(self, msg):
        return msg.status_code == 200 and msg.json()['header']['status'] == 4

    def isInvalidChallenge(self, msg):
        return msg.status_code == 200 and msg.json()['header']['status'] == 10

    def isInvalidFilename(self, msg):
        return msg.status_code == 200 and msg.json()['data']['result'] == 3

    def isBadRequest(self, msg):
        return msg.status_code == 400


# sec100 class, which provides functions to access all Evcam items of user level User and Maintenance
class sec100Client():
    def __init__(self, ip, p_user, p_password, mio_number="1144993", *args, **kwargs):
        self.ip = ip
        self.mio_number = mio_number
        self.p_user = p_user
        self.p_password = p_password
        # use the no_proxy sysenv variable to solve connection problems on some PCs
        if sys.platform.startswith('linux'):
            os.environ["no_proxy"] = ip
        elif sys.platform.startswith('win'):
            os.environ["NO_PROXY"] = ip

        self.com = self.init_dut( ip, p_user, p_password)

        self.minimal_compatible_fw_version = "0.2.0"
        fw_version = self.getExtendedFirmwareVersion()

        if not self.is_version_greater_or_equal(fw_version, self.minimal_compatible_fw_version):
            raise Exception("sec100Client not compatible with FW Version: Must be at least {}"
                            .format(self.minimal_compatible_fw_version))

        self.SnapshotNamingSettings = {'EnableTimestamp': True, 'EnableDevicename': False, 'EnableIterator': False, 'EnableUserText': False, 'Usertext': ''}
        self.EventNamingSettings = {'EnableTimestamp': True, 'EnableDevicename': False, 'EnableIterator': False,
                                       'EnableUserText': False, 'Usertext': ''}

    class ImageSize(Enum):
        IMAGE_2880x1616 = 6
        IMAGE_1920x1080 = 5
        IMAGE_1280x720 = 4
        IMAGE_640x360 = 3
        IMAGE_480x270 = 2
        IMAGE_320x180 = 1
        IMAGE_240x134 = 0

    class VideoCompressionType(Enum):
        H264 = 0
        H265 = 1

    class VideoCompressionRate(Enum):
        COMPRESSION_RATE_16383 = 16383
        COMPRESSION_RATE_8191 = 8191
        COMPRESSION_RATE_4095 = 4095
        COMPRESSION_RATE_2047 = 2047
        COMPRESSION_RATE_1023 = 1023

    class SnapshotImageFormat(Enum):
        JPEG = 0
        BMP = 1

    class FtpProtocol(Enum):
        FTP = 0
        sFTP = 1

    class EthernetAddressingMode(Enum):
        DHCP = 0
        Static = 1

    class HardwareTriggerActiveLevel(Enum):
        ActiveLow = 0
        ActiveHigh = 1

    class WatermarkingTextColor(Enum):
        Black = 1
        White = 2
        Red = 3
        Green = 4

    def init_dut(self, ip=None, *args, **kwargs):
        if ip is None:
            ip = self.ip
        return ChallengeResponseConnect(ip, *args, **kwargs)

    def re_init_dut(self, ip_new=None):
        ip = ip_new if ip_new else self.ip
        self.com = self.init_dut(ip, self.p_user, self.p_password)

    class LedStates(Enum):
        RDY_and_APP_always_off = 0
        RDY_and_APP_automatic_update = 1
        RDY_always_on_APP_always_off = 2
        RDY_always_off_APP_always_on = 3
        RDY_and_APP_always_on = 4

    def is_version_greater_or_equal(self, version_str, compare_version="0.1.0"):
        # Extract the version number part (e.g., "0.1.0" from "0.1.0-beta+local_build")
        match = re.match(r"(\d+\.\d+\.\d+)", version_str)
        if not match:
            raise ValueError("Invalid version string format")

        version = match.group(1)

        # Convert version strings to tuples of integers for comparison
        version_tuple = tuple(map(int, version.split('.')))
        compare_version_tuple = tuple(map(int, compare_version.split('.')))

        # Compare the version tuples
        result = version_tuple >= compare_version_tuple
        return result

    def getEventList(self):
        ret = self.com.make_get_request('/api/EventList')
        if self.com.isValidReply(ret):
            return ret.json()['data']['EventList']
        else:
            raise Exception(ret.json()['header']['message'])

    def downloadLatestSnapshot(self, file_path):
        snapshot_data = self.com.download_file('latestSnapshot')
        with open(file_path, 'wb') as f:
            f.write(snapshot_data)

    def downloadLatestEventRecording(self, file_path):
        snapshot_data = self.com.download_file('latestEventRecording')
        with open(file_path, 'wb') as f:
            f.write(snapshot_data)

    def downloadEvent(self, event_name, file_path):
        event_data = self.com.download_file(event_name)
        with open(file_path, 'wb') as f:
            f.write(event_data)

    def deleteAllFiles(self):
        self.setApiRequest("DeleteAllFiles")
        time0 = time.time()
        while time.time() - time0 < 60 and len(self.getEventList()) > 0:
            time.sleep(1)

    def deleteFile(self, fileName):
        ret = self.com.make_request('/api/DeleteFile', {"fileName": fileName})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

            # functions accessible by User
    def getEnableLiveView(self):
        ret = self.com.make_get_request('/api/EnableLiveView')
        if self.com.isValidReply(ret):
            return ret.json()['data']['EnableLiveView']
        else:
            raise Exception(ret.json()['header']['message'])

    def setEnableLiveView(self, enable):
        ret = self.com.make_request('/api/EnableLiveView', {"EnableLiveView": enable})
        if self.com.isAccessDenied(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getFileNamePrefix(self):
        ret = self.com.make_get_request('/api/FileNaming')
        if self.com.isValidReply(ret):
            return ret.json()['data']['FileNaming']
        else:
            raise Exception(ret.json()['header']['message'])

    def setFileNamePrefix(self, prefix:str):
        ret = self.com.make_request('/api/FileNaming', {"FileNaming": prefix})
        if self.com.isAccessDenied(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def triggerSnapshot(self):
        ret = self.com.make_request('/api/SnapshotTriggerSnapshot')
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        if ret.json()['data'].get("result"):
            if ret.json()['data']["result"] != 0:
                if ret.json()['data']["result"] == 1:
                    raise Exception("Snapshot disabled")
                else:
                    raise Exception("Snapshot busy")
        return self.com.isValidReply(ret)

    def triggerNamedSnapshot(self, name):
        ret = self.com.make_request('/api/SnapshotTriggerNamedSnapshot', {"SnapshotName": name})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        if ret.json()['data'].get("result"):
            if ret.json()['data']["result"] != 0:
                if ret.json()['data']["result"] == 1:
                    raise Exception("Snapshot disabled")
                else:
                    raise Exception("Snapshot busy")
        return self.com.isValidReply(ret)

    def triggerEvent(self):
        ret = self.com.make_request('/api/EventTriggerEvent')
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        if ret.json()['data'].get("result"):
            if ret.json()['data']["result"] != 0:
                if ret.json()['data']["result"] == 1:
                    raise Exception("Event Recording disabled")
                else:
                    raise Exception("Event Recording busy")
        return self.com.isValidReply(ret)

    def triggerNamedEvent(self, name):
        ret = self.com.make_request('/api/EventTriggerNamedEvent', {"EventName": name})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        if ret.json()['data'].get("result"):
            if ret.json()['data']["result"] != 0:
                if ret.json()['data']["result"] == 1:
                    raise Exception("Event Recording disabled")
                else:
                    raise Exception("Event Recording busy")
        return self.com.isValidReply(ret)

    def getImageRotation(self):
        ret = self.com.make_get_request('/api/ImageRotation')
        if self.com.isValidReply(ret):
            sopas_flag = ret.json()['data']['ImageRotation']
            rotation = 90*sopas_flag
            return rotation
        else:
            raise Exception(ret.json()['header']['message'])

    def setImageRotation(self, rotation: int):
        if rotation not in [0, 90, 180, 270]:
            raise ValueError("Invalid rotation value. Valid values are 0, 90, 180, and 270.")

        sopas_flag = int(rotation/90)
        ret = self.com.make_request('/api/ImageRotation', {"ImageRotation": sopas_flag})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getVideo0ImageResolution(self) -> ImageSize:
        ret = self.com.make_get_request('/api/Video0Resolution')
        if self.com.isValidReply(ret):
            resolution_value = ret.json()['data']['Video0Resolution']
            resolution = self.ImageSize(resolution_value)
            return resolution
        else:
            raise Exception(ret.json()['header']['message'])

    def getVideo1ImageResolution(self) -> ImageSize:
        ret = self.com.make_get_request('/api/Video1Resolution')
        if self.com.isValidReply(ret):
            resolution_value = ret.json()['data']['Video1Resolution']
            resolution = self.ImageSize(resolution_value)
            return resolution
        else:
            raise Exception(ret.json()['header']['message'])

    def getImageResolution(self) -> ImageSize:
        return self.getVideo1ImageResolution()

    def setVideo0ImageResolution(self, resolution: ImageSize):
        if not isinstance(resolution, self.ImageSize):
            raise ValueError("Invalid resolution value. Please use the ImageSize enum.")

        ret = self.com.make_request('/api/Video0Resolution', {"Video0Resolution": resolution.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    def setVideo1ImageResolution(self, resolution: ImageSize):
        if not isinstance(resolution, self.ImageSize):
            raise ValueError("Invalid resolution value. Please use the ImageSize enum.")

        ret = self.com.make_request('/api/Video1Resolution', {"Video1Resolution": resolution.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    # just keep the function for compatibility reasons (video0 is assumed as default)
    def setImageResolution(self, resolution: ImageSize):
        return self.setVideo0ImageResolution(resolution)

    def setVideo0EncoderGop(self, gop: int):
        self.setApiRequest("Video0EncoderGop", gop)

    def getVideo0EncoderGop(self) -> int:
        return self.getApiReply("Video0EncoderGop")

    def setVideo1EncoderGop(self, gop: int):
        self.setApiRequest("Video1EncoderGop", gop)

    def getVideo1EncoderGop(self) -> int:
        return self.getApiReply("Video1EncoderGop")

    @deprecated
    def getEnableAutoExposureMode(self) -> bool:
        return self.getAutoExposureMode()

    def getAutoExposureMode(self) -> bool:
        return self.getApiReply("ImageAutoExposureMode")

    @deprecated
    def setEnableAutoExposureMode(self, enableAutoExposureMode: bool):
        return self.setAutoExposureMode(enableAutoExposureMode)

    def setAutoExposureMode(self, enableAutoExposureMode: bool):
        ret = self.com.make_request('/api/ImageAutoExposureMode', {"ImageAutoExposureMode": enableAutoExposureMode})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    @deprecated
    def getExposureTime(self) -> float:
        return self.getImageExposureTime()

    def getImageExposureTime(self) -> float:
        return self.getApiReply("ImageExposureTime")

    @deprecated
    def setExposureTime(self, exposureTime: float):
        return self.setImageExposureTime(exposureTime)

    def setImageExposureTime(self, exposureTime: float):
        if exposureTime > 1.0 or exposureTime < 0:
            raise ValueError("Invalid exposureTime value. Valid values 0 <= exposureTime <= 1.0")

        ret = self.com.make_request('/api/ImageExposureTime', {"ImageExposureTime": exposureTime})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    @deprecated
    def getEnableAutoGainMode(self) -> bool:
        return self.getImageAutoGainMode()

    def getImageAutoGainMode(self) -> bool:
        return self.getApiReply("ImageAutoGainMode")

    @deprecated
    def setEnableAutoGainMode(self, enableAutoGainMode: bool):
        return self.setImageAutoGainMode(enableAutoGainMode)

    def setImageAutoGainMode(self, enableAutoGainMode: bool):
        ret = self.com.make_request('/api/ImageAutoGainMode', {"ImageAutoGainMode": enableAutoGainMode})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    @deprecated
    def getGain(self) -> float:
        return self.getImageGain()

    def getImageGain(self):
        return self.getApiReply("ImageGain")

    @deprecated
    def setGain(self, gain: int):
        return self.setImageGain(gain)

    def setImageGain(self, gain: int):
        ret = self.com.make_request('/api/ImageGain', {"ImageGain": gain})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    @deprecated
    def getSharpness(self) -> int:
        return self.getImageSharpness()

    def getImageSharpness(self) -> int:
        return self.getApiReply("ImageSharpness")

    @deprecated
    def setSharpness(self, sharpness: int):
        return self.setImageSharpness(sharpness)

    def setImageSharpness(self, sharpness: int):
        if sharpness > 100 or sharpness < 0:
            raise ValueError("Invalid sharpness value. Valid values 0% ... 100%")

        ret = self.com.make_request('/api/ImageSharpness', {"ImageSharpness": sharpness})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    def getVideo0FrameRate(self) -> int:
        ret = self.com.make_get_request('/api/Video0FrameRate')
        if self.com.isValidReply(ret):
            return ret.json()['data']['Video0FrameRate']
        else:
            raise Exception(ret.json()['header']['message'])

    def getVideo1FrameRate(self) -> int:
        ret = self.com.make_get_request('/api/Video1FrameRate')
        if self.com.isValidReply(ret):
            return ret.json()['data']['Video1FrameRate']
        else:
            raise Exception(ret.json()['header']['message'])

    # just keep the function for compatibility reasons (video0 is assumed as default)
    def getFrameRate(self) -> int:
        return self.getVideo0FrameRate()

    def setVideo0FrameRate(self, frameRate: int):
        ret = self.com.make_request('/api/Video0FrameRate', {"Video0FrameRate": frameRate})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    def setVideo1FrameRate(self, frameRate: int):
        if frameRate > 60 or frameRate < 0:
            raise ValueError("Invalid FrameRate value. Valid values 0 ... 60")

        ret = self.com.make_request('/api/Video1FrameRate', {"Video1FrameRate": frameRate})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    # just keep the function for compatibility reasons (video0 is assumed as default)
    def setFrameRate(self, frameRate: int):
        return self.setVideo0FrameRate(frameRate)

    def getApiReply(self, api_key: str):
        ret = self.com.make_get_request('/api/' + api_key)
        if self.com.isValidReply(ret):
            return ret.json()['data'][api_key]
        else:
            raise Exception(ret.json()['header']['message'])

    def setApiRequest(self, api_key, value=None, timeout=None):
        if value is not None:
            ret = self.com.make_request(uri=f'/api/{api_key}', data = {api_key: value}, timeout=timeout)
        else:
            ret = self.com.make_request(uri=f'/api/{api_key}', timeout=timeout)
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def setVideo0EncoderBitrate(self, bitrate: VideoCompressionRate):
        if not isinstance(bitrate, self.VideoCompressionRate):
            raise ValueError("Invalid bitrate value. Valid values are: {}".format([e.value for e in self.VideoCompressionRate]))

        ret = self.com.make_request('/api/Video0CompressionRate', {"Video0CompressionRate": bitrate.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])

        return self.com.isValidReply(ret)

    def setVideo1EncoderBitrate(self, bitrate: VideoCompressionRate):
        if not isinstance(bitrate, self.VideoCompressionRate):
            raise ValueError("Invalid bitrate value. Valid values are: {}".format([e.value for e in self.VideoCompressionRate]))

        ret = self.com.make_request('/api/Video1CompressionRate', {"Video1CompressionRate": bitrate.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getVideo0EncoderBitrate(self) -> VideoCompressionRate:
        compression = self.getApiReply('Video0CompressionRate')
        return self.VideoCompressionRate(compression)

    def getVideo1EncoderBitrate(self) -> VideoCompressionRate:
        compression =  self.getApiReply('Video1CompressionRate')
        return self.VideoCompressionRate(compression)

    def LoadFactoryDefaults(self):
        try:
            ret = self.setApiRequest("LoadFactoryDefaults", timeout=30)
        except:
            ret = False
            print("timeout due to Ip change after factory reset or other error")
        return ret

    def rebootDevice(self):
        return self.setApiRequest("RebootDevice")

    def getOrderNumber(self) -> bool:
        return self.getApiReply('OrderNumber')

    def setOrderNumber(self, value: str):
        return self.setApiRequest('OrderNumber', value)

    def getTypeCode(self) -> bool:
        return self.getApiReply('TypeCode')

    def setTypeCodeSEC100(self):
        return self.setApiRequest('TypeCode', "SEC100-5C9D1SFZZZZ")

    def setTypeCodeSEC110(self):
        return self.setApiRequest('TypeCode', "SEC110-5C9D1SFZZZZ")


    def getVendorID(self) -> bool:
        return self.getApiReply('Vendor')

    def getFirmwareVersion(self) -> bool:
        return self.getApiReply('FirmwareVersion')

    def getExtendedFirmwareVersion(self) -> bool:
        return self.getApiReply('ExtendedFirmwareVersion')

    def getDeviceName(self) -> str:
        return self.getApiReply('DeviceName')

    def setDeviceName(self, deviceName) -> bool:
        return self.setApiRequest("DeviceName", deviceName)

    def getLocationName(self) -> str:
        return self.getApiReply('LocationName')

    def setLocationName(self, locationName) -> bool:
        return self.setApiRequest("LocationName", locationName)

    def setVideo0CompressionType(self, compression: VideoCompressionType):
        if not isinstance(compression, self.VideoCompressionType):
            raise ValueError("Invalid resolution value. Please use the VideoCompressionType enum.")
        ret = self.com.make_request('/api/Video0CompressionType', {"Video0CompressionType": compression.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def setVideo1CompressionType(self, compression: VideoCompressionType):
        if not isinstance(compression, self.VideoCompressionType):
            raise ValueError("Invalid resolution value. Please use the VideoCompressionType enum.")
        ret = self.com.make_request('/api/Video1CompressionType', {"Video1CompressionType": compression.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getVideo0CompressionType(self) -> VideoCompressionType:
        return self.getApiReply("Video0CompressionType")

    def getVideo1CompressionType(self) -> VideoCompressionType:
        return self.getApiReply("Video1CompressionType")

    def getRtspPort(self):
        return self.getApiReply('RtspPort')

    def getVideo0RtspPath(self):
        return self.getApiReply('Video0RtspPath')

    def getVideo1RtspPath(self):
        return self.getApiReply('Video1RtspPath')

    def setVideo0EnableRtsp(self, value:bool):
        return self.setApiRequest("Video0EnableRtsp", value)

    def setVideo1EnableRtsp(self, value:bool):
        return self.setApiRequest("Video1EnableRtsp", value)

    def getVideo0EnableRtsp(self):
        return self.getApiReply("Video0EnableRtsp")

    def getVideo1EnableRtsp(self):
        return self.getApiReply("Video1EnableRtsp")

    def setRtspAuthenticationEnabled(self, value:bool):
        return self.setApiRequest("RtspAuthenticationEnabled", value)

    def getRtspAuthenticationEnabled(self):
        return self.getApiReply("RtspAuthenticationEnabled")

    def setEventEnableRecording(self, enableEventRecording:int):
        return self.setApiRequest("EventEnableRecording", enableEventRecording)

    def getEventEnableRecording(self) ->bool:
        return self.getApiReply("EventEnableRecording")

    def getSnapshotMode(self):
        return self.getApiReply('SnapshotMode')

    def setSnapshotMode(self, value:int):
        if not value in [0, 1]:
            raise ValueError("Invalid value, must be one of [0, 1]")
        return self.setApiRequest("SnapshotMode", value)

    def getSnapshotImageFormat(self) -> SnapshotImageFormat:
        imageFormat = self.getApiReply('SnapshotImageFormat')
        return self.SnapshotImageFormat(imageFormat)

    def setSnapshotImageFormat(self, imageFormat: SnapshotImageFormat):
        if not isinstance(imageFormat, self.SnapshotImageFormat):
            raise ValueError("Invalid Snapshot Image Format value. Valid values are: {}".format([e.value for e in self.SnapshotImageFormat]))

        ret = self.com.make_request('/api/SnapshotImageFormat', {"SnapshotImageFormat": imageFormat.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getSnapshotNaming(self) -> dict:
        return self.getApiReply('SnapshotNaming')

    def setSnapshotNaming(self, naming_settings: dict):
        ret = self.com.make_request('/api/SnapshotNaming', {"SnapshotNaming": naming_settings})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getSnapshotJpegCompression(self):
        return self.getApiReply('SnapshotJpegCompression')

    def setSnapshotJpegCompression(self, value:int):
        if not 10 <= value <= 99:
            raise Exception("value not in range 10 - 99")
        return self.setApiRequest("SnapshotJpegCompression", value)

    def setSnapshotEnableJpgSuffix(self, value:bool):
        return self.setApiRequest("SnapshotEnableJpgSuffix", value)

    def getSnapshotEnableJpgSuffix(self):
        return self.getApiReply("SnapshotEnableJpgSuffix")

    def getEventNaming(self) -> dict:
        return self.getApiReply('EventNaming')

    def setEventNaming(self, naming_settings: dict):
        ret = self.com.make_request('/api/EventNaming', {"EventNaming": naming_settings})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def setFtpProtocol(self, protocol: FtpProtocol):
        if not isinstance(protocol, self.FtpProtocol):
            raise ValueError("Invalid protocol value. Please use the FtpProtocol enum.")
        ret = self.com.make_request('/api/FtpProtocol', {"FtpProtocol": protocol.value})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getFtpProtocol(self) -> FtpProtocol:
        return self.getApiReply("FtpProtocol")

    def getFtpServerAddress(self):
        return self.getApiReply("FtpServerAddress")

    def setFtpServerAddress(self, address: list[int]):
        if len(address) != 4:
            raise ValueError("Invalid ip address, shall be a list of 4 integers.")
        self.setApiRequest("FtpServerAddress", address)

    def getFtpPort(self):
        return self.getApiReply("FtpPort")

    def setFtpPort(self, value:int):
        return self.setApiRequest("FtpPort", value)

    def getFtpServerDirectory(self):
        return self.getApiReply("FtpServerDirectory")

    def setFtpServerDirectory(self, value:str):
        return self.setApiRequest("FtpServerDirectory", value)

    def getFtpEnableFallbackMode(self):
        return self.getApiReply("FtpEnableFallbackMode")

    def setFtpEnableFallbackMode(self, value:bool):
        return self.setApiRequest("FtpEnableFallbackMode", value)

    def getFtpUserName(self):
        return self.getApiReply("FtpUserName")

    def setFtpUserName(self, value:str):
        return self.setApiRequest("FtpUserName", value)

    def getFtpPassword(self):
        return self.getApiReply("FtpPassword")

    def setFtpPassword(self, value:str):
        return self.setApiRequest("FtpPassword", value)

    def getFtpEnablePassiveMode(self):
        return self.getApiReply("FtpEnablePassiveMode")

    def setFtpEnablePassiveMode(self, value:bool):
        return self.setApiRequest("FtpEnablePassiveMode", value)

    def setFtpConnectToServer(self):
        return self.setApiRequest("FtpConnectToServer")

    def getDeviceStatus(self):
        return self.getApiReply("DeviceStatus")

    def getDeviceStatusRTSP0(self):
        return self.getApiReply("DeviceStatusRTSP0")

    def getDeviceStatusRTSP1(self):
        return self.getApiReply("DeviceStatusRTSP1")

    def getDeviceStatusLiveView(self):
        return self.getApiReply("DeviceStatusLiveView")

    def setEnableHttpLiveView(self, enable:bool):
        return self.setApiRequest("EnableHttpLiveView", enable)

    def getDeviceStatusHttpLiveView(self):
        return self.getApiReply("DeviceStatusHttpLiveView")

    def getDeviceStatusFTP(self):
        return self.getApiReply("DeviceStatusFTP")

    def getDeviceStatusNTP(self):
        return self.getApiReply("DeviceStatusNTP")

    def getDeviceStatusStorageUsage(self):
        return self.getApiReply("DeviceStatusStorageUsage")

    def getDeviceStatusDeviceTime(self):
        return self.getApiReply("DeviceStatusDeviceTime")

    def getCurrentTemperature(self):
        return self.getApiReply("CurrentTemperature")

    def getTotalOperatingHours(self):
        return self.getApiReply("TotalOperatingHours")

    def getTotalOpHours(self):
        # retruns the opHours as 1/10 hours
        return self.getApiReply("OpHours") / 10

    def getDailyOpHours(self):
        return self.getApiReply("DailyOpHours")

    def getPowerOnCount(self):
        return self.getApiReply("PowerOnCnt")

    def getTotalOperatingHoursSinceLastReset(self):
        return self.getApiReply("TotalOperatingHoursSinceLastReset")

    def ResetDiagnosticParameters(self):
        return self.setApiRequest("ResetDiagnosticParameters")

    def setEtherAddressingMode(self, value: EthernetAddressingMode):
        return self.setApiRequest("EtherAddressingMode", value)

    def getEtherAddressingMode(self) -> EthernetAddressingMode:
        return self.getApiReply("EtherAddressingMode")

    def setEtherIPAddress(self, value:list[int]):
        if len(value) != 4:
            raise ValueError("Invalid ip address, shall be a list of 4 integers.")
        return self.setApiRequest("EtherIPAddress", value)

    def setEtherUpdateNeeded(self, enable:bool):
        return self.setApiRequest("EtherUpdateNeeded", enable)

    def setEtherUpdate(self):
        return self.setApiRequest('EthernetUpdate', timeout=0.5)

    def getEtherIPAddress(self):
        return self.getApiReply("EtherIPAddress")

    def getEtherSubnetMask(self):
        return self.getApiReply("EtherSubnetMask")

    def getEtherMACAddress(self):
        return self.getApiReply("EtherMACAddress")

    def setEtherMACAddress(self, mac_address: list[int]):
        if len(mac_address) != 6:
            raise ValueError("Invalid MAC address, shall be a list of 6 integers.")
        return self.setApiRequest("EtherMACAddress", mac_address)

    def getEtherIPSpeedDuplex(self):
        return self.getApiReply("EtherIPSpeedDuplex")

    def getEtherDHCPFallback(self):
        return self.getApiReply("EtherDHCPFallback")

    def getEtherIPGateAddress(self):
        return self.getApiReply("EtherIPGateAddress")

    def setSnapshotHardwareTrigger(self, enable:bool):
        return self.setApiRequest("SnapshotHardwareTrigger", enable)

    def getSnapshotHardwareTrigger(self):
        return self.getApiReply("SnapshotHardwareTrigger")

    def getHardwareTriggerActiveLevel(self) -> HardwareTriggerActiveLevel:
        return self.getApiReply("HardwareTriggerActiveLevel")

    def setHardwareTriggerActiveLevel(self, value:HardwareTriggerActiveLevel):
        return self.setApiRequest("HardwareTriggerActiveLevel", value.value)

    def getHardwareTriggerTonDelay(self):
        return self.getApiReply("HardwareTriggerTonDelay")

    def setHardwareTriggerTonDelay(self, value:int):
        return self.setApiRequest("HardwareTriggerTonDelay", value)

    def setHardwareTriggerState(self, value):
        return self.setApiRequest("HardwareTriggerState", value)

    def getHardwareTriggerState(self):
        return self.getApiReply("HardwareTriggerState")

    def getHardwareTriggerLastActiveState(self):
        return self.getApiReply("HardwareTriggerLastActiveState")

    def setTimeServerAddress(self, value:list[int]):
        if len(value) != 4:
            raise ValueError("Invalid address, shall be a list of 4 integers.")
        return self.setApiRequest("TSCTCSrvAddr", value)

    def getTimeServerAddress(self):
        return self.getApiReply("TSCTCSrvAddr")

    def setTimeServerUpdateTime(self, value:int):
        return self.setApiRequest("TSCTCupdatetime", value)

    def getTimeServerUpdateTime(self):
        return self.getApiReply("TSCTCupdatetime")

    def setTimeSync(self, state):
        return self.setApiRequest("TSCRole", state)

    def getTimeSync(self):
        return self.getApiReply("TSCRole")

    def setTimeZone(self, time_zone: int):
        return self.setApiRequest('TSCTCtimezone', time_zone)

    def getTimeZone(self):
        return self.getApiReply('TSCTCtimezone')

    def setEventTimeBeforeTrigger(self, value:int):
        return self.setApiRequest("EventTimeBeforeTrigger", value)

    def getEventTimeBeforeTrigger(self):
        return self.getApiReply("EventTimeBeforeTrigger")

    def setEventTimeAfterTrigger(self, value:int):
        return self.setApiRequest("EventTimeAfterTrigger", value)

    def getEventTimeAfterTrigger(self):
        return self.getApiReply("EventTimeAfterTrigger")

    def setEventHardwareTrigger(self, value:bool):
        return self.setApiRequest("EventEnableHardwareTrigger", value)

    def getEventHardwareTrigger(self):
        return self.getApiReply("EventEnableHardwareTrigger")

    def getUserLevels(self):
        ret = self.com.make_request('/api/GetUserLevelInformation')
        return ret.json()['data']["userLevels"]

    def setLedState(self, state:LedStates):
        return self.setApiRequest("LedsEnable", state.value)

    def getLedState(self):
        return self.getApiReply("LedsEnable")

    def setDeviceStatusGpoState(self, value: bool):
        return self.setApiRequest("DeviceStatusGpoState", value)

    def getDeviceStatusGpoState(self):
        return self.getApiReply("DeviceStatusGpoState")

    def StartLiveRecording(self):
        return self.setApiRequest("StartLiveRecording")

    def StopLiveRecording(self):
        return self.setApiRequest("StopLiveRecording")

    def setSambaEnabled(self, value: bool):
        return self.setApiRequest("SetSambaEnabled", value)

    def getSambaEnabled(self):
        return self.getApiReply("SetSambaEnabled")

    def setTcpIpTriggerEnabled(self, value: bool):
        return self.setApiRequest("SetTcpIpTriggerEnabled", value)

    def getTcpIpTriggerEnabled(self):
        return self.getApiReply("SetTcpIpTriggerEnabled")

    def setEnableEventRecording(self, value:bool):
        message = {"enableEventRecording": value}
        return self.setApiRequest("setFeatureSet", message)
    def getSnapshotNewFileAvailable(self):
        return self.getApiReply("SnapshotNewFileAvailable")

    def getEventNewFileAvailable(self):
        return self.getApiReply("EventNewFileAvailable")

    def setWatermarkingTextColor(self, color:WatermarkingTextColor):
        return self.setApiRequest("WatermarkingTextColor", color.value)

    def getWatermarkingTextColor(self) -> WatermarkingTextColor:
        return self.getApiReply("WatermarkingTextColor")

    def setEnableEolTest(self, enable: bool):
        ret = self.com.make_request('/api/enableEolTest', {"enableEolTest": enable})
        if self.com.isAccessDenied(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def getEnableEolTest(self):
        return self.getApiReply("enableEolTest")

    def getImageRoi(self):
        return self.getApiReply('ImageRoi')

    def setImageRoi(self, data: dict):
        return self.setApiRequest('ImageRoi', data)

    def setImageAutomatedAdjustment(self, value: bool):
        return self.setApiRequest("ImageAutomatedAdjustment", value)

    def getImageAutomatedAdjustment(self):
        return self.getApiReply("ImageAutomatedAdjustment")

    def setAuthenticationFreeApiEnabled(self, value):
        return self.setApiRequest("SetAuthenticationFreeApiEnabled", value)

    def SetTcpIpTriggerEnabled(self, value):
        return self.setApiRequest("SetTcpIpTriggerEnabled", value)

    def setTcpIpTriggerPort(self, port):
        return self.setApiRequest("TcpIpTriggerPort", port)

    def getTcpIpTriggerPort(self):
        return self.getApiReply("TcpIpTriggerPort")

    def setEnableSoftwareDowngrade(self, enable: bool):
        return self.setApiRequest('EnableSoftwareDowngrade', enable)

    def getEnableSoftwareDowngrade(self):
        return self.getApiReply("EnableSoftwareDowngrade")

    def getEtherCoLa2Enabled(self):
        return self.getApiReply("EtherCoLa2Enabled")

    def getLiveSnapshot(self):
        return self.com.make_get_request('/authenticationFree/liveJpegImage')

    def checkCredentials(self):
        return self.com.make_request("/api/checkCredentials")

    def getLSPdatetime(self):
        return self.getApiReply("LSPdatetime")

    def timeToDict(self):
        t0 = datetime.now()
        return  {"uiYear": t0.year, "usiMonth": t0.month, "usiDay": t0.day, "usiHour": t0.hour, "usiMinute": t0.minute,
                  "usiSec": t0.second, "udiUSec": t0.microsecond}

    def dictToTime(self, time_dict):
        dt = datetime(
            year=time_dict["uiYear"],
            month=time_dict["usiMonth"],
            day=time_dict["usiDay"],
            hour=time_dict.get("usiHour", 0),
            minute=time_dict.get("usiMinute", 0),
            second=time_dict.get("usiSec", 0)
        )
        dt_berlin = dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        return dt_berlin.timestamp()

    def LSPsetdatetime(self):
        t_dict = self.timeToDict()
        return self.com.make_request(uri=f'/api/LSPsetdatetime', data = {"DateTime": t_dict}, timeout=None)

    def copyFileFromDevice(self, ssh_key, file_path_device, target_path):
        cmd = f"scp -vvv -i {ssh_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{self.ip}:{file_path_device} " + target_path
        result = subprocess.run(cmd, capture_output=True, shell=True, text=True, timeout=30)
        return result

    def copyFileToDevice(self, ssh_key, file_path, target_path_device):
        cmd = f"scp -i {ssh_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {file_path} root@{self.ip}:{target_path_device}"
        return subprocess.run(cmd, capture_output=True, shell=True, text=True)

    def postRequestNoAuthentification(self, address):
        ret = requests.post(address, verify=False)
        if self.com.isInvalidChallenge(ret):
            print(f"Get new challenge due to invalid Challenge {self.com.isInvalidChallenge(ret)}")
            self.com.get_challenge()
            ret = requests.post(address, verify=False)

        if self.com.isBadRequest(ret):
            raise Exception("Bad request")
        elif self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        elif self.com.isInvalidFilename(ret):
            raise Exception("Invalid filename")

        return self.com.isValidReply(ret)

    def SetAuthenticationFreeApiEnabled(self, enable:bool):
        return self.setApiRequest("SetAuthenticationFreeApiEnabled", enable)

    def GetAuthenticationFreeApiEnabled(self):
        return self.getApiReply("SetAuthenticationFreeApiEnabled")

    def SnapshotTriggerNamedSnapshot(self, name:str):
        ret = self.com.make_request('/api/SnapshotTriggerNamedSnapshot', {"SnapshotName": name})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)

    def EventTriggerNamedEvent(self, name:str):
        ret = self.com.make_request('/api/EventTriggerNamedEvent', {"EventName": name})
        if self.com.isAccessDenied(ret) or not self.com.isValidReply(ret):
            raise Exception(ret.json()['header']['message'])
        return self.com.isValidReply(ret)
