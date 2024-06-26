import hashlib
import hmac
import os
import random
import string
import time
import uuid
import json

from aiohttp import ClientSession

from alibabacloud_iot_api_gateway.models import Config, IoTApiRequest, CommonParams
from alibabacloud_iot_api_gateway.client import Client
from alibabacloud_tea_util.models import RuntimeOptions

from alibabacloud_tea_util.client import Client as UtilClient

import base64

from pyluba.utility.datatype_converter import DatatypeConverter


from pyluba.aliyun.dataclass.regionsResponse import RegionResponse
from pyluba.aliyun.dataclass.connectResponse import ConnectResponse
from pyluba.aliyun.dataclass.loginByOAuthResponse import LoginByOAuthResponse
from pyluba.aliyun.dataclass.aepResponse import AepResponse
from pyluba.aliyun.dataclass.sessionByAuthCodeResponse import SessionByAuthCodeResponse
from pyluba.aliyun.dataclass.listingDevByAccountResponse import ListingDevByAccountResponse

from pyluba.aliyun.constant import Constant

# init client


MOVE_HEADERS = (
    "x-ca-signature",
    "x-ca-signature-headers",
    "accept",
    "content-md5",
    "content-type",
    "date",
    "host",
    "token",
    "user-agent"
)


class CloudIOTGateway:

    _client_id = ""
    _device_sn = ""
    _utdid = ""

    _connectResponse = None
    _loginByOAuthResponse = None
    _aepResponse = None
    _sessionByAuthCodeResponse = None
    _listingDevByAccountResponse = None
    _region = None

    converter = DatatypeConverter()

    def __init__(self):
        self._app_key = Constant.APP_KEY
        self._app_secret = Constant.APP_SECRET
        self.domain = 'api.link.aliyun.com'

        uuid1 = str(uuid.uuid1())  # 128 chatarrers
        self._client_id = uuid1[:8]  # First 8 Characters
        self._device_sn = uuid1.replace("-", "")[:32]
        self._utdid = self.generate_random_string(32)  # 32 Characters

    @staticmethod
    def generate_random_string(length):
        characters = string.ascii_letters + string.digits
        random_string = ''.join(random.choice(characters) for _ in range(length))
        return random_string

    def sign(self, data):
        keys = ["appKey", "clientId", "deviceSn", "timestamp"]
        concatenated_str = ""
        for key in keys:
            concatenated_str += f"{key}{data.get(key, '')}"

        print(f"sign(), toSignStr = {concatenated_str}")

        sign = hmac.new(self._app_secret.encode('utf-8'), concatenated_str.encode("utf-8"), hashlib.sha1).hexdigest()

        return sign

    def get_region(self, countryCode: str, authCode: str):
        # shim out the regions?
        #  https://api.link.aliyun.com/living/account/region/get?x-ca-request-id=59abc767-fbbc-4333-9127-e65d792133a8
        # x-ca-request-id is a random UUID on each request

        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=self.domain
        )
        client = Client(config)

        # build request
        request = CommonParams(api_ver='1.0.2', language='en-US')
        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params={
                "authCode": authCode,
                "type": "THIRD_AUTHCODE",
                "countryCode": countryCode
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/living/account/region/get',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        # Decodifica il corpo della risposta
        response_body_str = response.body.decode('utf-8')

        # Carica la stringa JSON in un dizionario
        response_body_dict = json.loads(response_body_str)

        if int(response_body_dict.get('code')) != 200:
            raise Exception ('Error in getting regions: ' + response_body_dict["msg"])
        else:
            self._region = RegionResponse.from_dict(response_body_dict) 
            print("Endpoint : " + self._region.data.mqttEndpoint)
    
        

        return response.body

    def aep_handle(self):

        # https://api.link.aliyun.com/app/aepauth/handle
        aep_domain = self.domain

        if self._region.data.apiGatewayEndpoint is not None:
            aep_domain = self._region.data.apiGatewayEndpoint

        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=aep_domain
        )
        client = Client(config)

        request = CommonParams(api_ver='1.0.0', language='en-US')
        print("client id ", self._client_id)
        time_now = time.time()
        data_to_sign = {
            'appKey': self._app_key,
            "clientId": self._client_id,  # needs to be unique to device
            "deviceSn": self._device_sn,  # same here
            "timestamp": str(time_now)
        }

        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params={
                "authInfo": {
                    "clientId": self._client_id,
                    "sign": self.sign(data_to_sign),
                    "deviceSn": self._device_sn,
                    "timestamp": str(time_now)
                }
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/app/aepauth/handle',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        response_body_str = response.body.decode('utf-8')

        response_body_dict = json.loads(response_body_str)
        
        if int(response_body_dict.get('code')) != 200:
            raise Exception ('Error in getting mqtt credentials: ' + response_body_dict["msg"])
        else:
            self._aepResponse = AepResponse.from_dict(response_body_dict)

        logger.debug(response_body_dict)

        return response.body

    # returns vid

    async def connect(self):
        region_url = "sdk.openaccount.aliyun.com"
        async with ClientSession() as session:
            headers = {
                'host': region_url,
                'date': UtilClient.get_date_utcstring(),
                'x-ca-nonce': UtilClient.get_nonce(),
                'x-ca-key': self._app_key,
                'x-ca-signaturemethod': 'HmacSHA256',
                'accept': 'application/json',
                'content-type': 'application/x-www-form-urlencoded',
                'user-agent': UtilClient.get_user_agent(None)
            }

            _bodyParam = {

                "context":
                    {
                        "sdkVersion": "3.4.2",
                        "platformName": "android",
                        "netType": "wifi",
                        "appKey": self._app_key,
                        "yunOSId": "",
                        "appVersion": "1.11.188",
                        "utDid": self._utdid,
                        "appAuthToken": self._utdid,  # ???
                        "securityToken": self._utdid  # ???
                    },
                "config": {
                    "version": 0,
                    "lastModify": 0
                },
                "device": {
                    "model": "sdk_gphone_x86_arm",
                    "brand": "goldfish_x86",
                    "platformVersion": "30"
                }

            }

            # Get sign header
            dic = headers.copy()
            for key in MOVE_HEADERS:
                dic.pop(key, None)

            keys = sorted(dic.keys())
            sign_headers = ','.join(keys)
            header = ''.join(f'{k}:{dic[k]}\n' for k in keys).strip()

            headers['x-ca-signature-headers'] = sign_headers
            string_to_sign = 'POST\n{}\n\n{}\n{}\n{}\n/api/prd/connect.json?request={}'.format(
                headers['accept'],
                headers['content-type'],
                headers['date'],
                header,
                json.dumps(_bodyParam, separators=(',', ':'))
            )

            hash_val = hmac.new(self._app_secret.encode('utf-8'), string_to_sign.encode('utf-8'),
                                hashlib.sha256).digest()
            signature = base64.b64encode(hash_val).decode('utf-8')
            headers['x-ca-signature'] = signature

            async with session.post(f'https://{region_url}/api/prd/connect.json',
                                    headers=headers,
                                    params=dict(
                                        request=json.dumps(_bodyParam, separators=(',', ':'))
                                    )
                                    ) as resp:
                data = await resp.json()
                self._connectResponse = ConnectResponse.from_dict(data)
                print(data)

    async def login_by_oauth(self, countryCode: str, authCode: str):
        """loginbyoauth.json."""

        region_url = self._region.data.oaApiGatewayEndpoint

        async with ClientSession() as session:
            headers = {
                'host': region_url,
                'date': UtilClient.get_date_utcstring(),
                'x-ca-nonce': UtilClient.get_nonce(),
                'x-ca-key': self._app_key,
                'x-ca-signaturemethod': 'HmacSHA256',
                'accept': 'application/json',
                'content-type': 'application/x-www-form-urlencoded',
                'user-agent': UtilClient.get_user_agent(None),
                'vid': self._connectResponse.data.vid
            }

            _bodyParam = {
                "country": countryCode,
                "authCode": authCode,
                "oauthPlateform": "23",
                "oauthAppKey": self._app_key,
                "appAuthToken": self._device_sn,
                "riskControlInfo": {
                    "appID": "com.agilexrobotics",
                    "signType": "RSA",
                    "utdid": self._utdid,
                    "umidToken": self._utdid,
                    "USE_OA_PWD_ENCRYPT": "true",
                    "USE_H5_NC": "true"
                }
            }

            # Get sign header
            dic = headers.copy()
            for key in MOVE_HEADERS:
                dic.pop(key, None)

            keys = sorted(dic.keys())
            sign_headers = ','.join(keys)
            header = ''.join(f'{k}:{dic[k]}\n' for k in keys).strip()

            headers['x-ca-signature-headers'] = sign_headers
            string_to_sign = 'POST\n{}\n\n{}\n{}\n{}\n/api/prd/loginbyoauth.json?loginByOauthRequest={}'.format(
                headers['accept'],
                headers['content-type'],
                headers['date'],
                header,
                json.dumps(_bodyParam, separators=(',', ':'))
            )

            hash_val = hmac.new(self._app_secret.encode('utf-8'), string_to_sign.encode('utf-8'),
                                hashlib.sha256).digest()
            signature = base64.b64encode(hash_val).decode('utf-8')
            headers['x-ca-signature'] = signature

            async with session.post(f'https://{region_url}/api/prd/loginbyoauth.json',
                                    headers=headers,
                                    params=dict(
                                        loginByOauthRequest=json.dumps(_bodyParam, separators=(',', ':'))
                                    )
                                    ) as resp:
                data = await resp.json()
                print(data)

                self._loginByOAuthResponse = LoginByOAuthResponse.from_dict(data)

        # self._region = response.body.data

        # return response.body

        # headers require sid vid or at a minimuim vid which comes from prd/connect.json

    def session_by_auth_code(self):

        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=self._region.data.apiGatewayEndpoint
        )
        client = Client(config)

        # build request
        request = CommonParams(api_ver='1.0.4', language='en-US')
        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params=
            {
                "request":
                    {
                        "authCode": self._loginByOAuthResponse.data.data.loginSuccessResult.sid,
                        "accountType": "OA_SESSION",
                        "appKey": self._app_key
                    }
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/account/createSessionByAuthCode',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        # self._region = response.body.data
        # Decodifica il corpo della risposta
        response_body_str = response.body.decode('utf-8')

        # Carica la stringa JSON in un dizionario
        response_body_dict = json.loads(response_body_str)

        if int(response_body_dict.get('code')) != 200:
            raise Exception ('Error in creating session: ' + response_body_dict["msg"])
        else:
            self._sessionByAuthCodeResponse = SessionByAuthCodeResponse.from_dict(response_body_dict)

        return response.body
    
    def check_or_refresh_session(self):
        if self.load_saved_params() == False:
            return False
        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=self._region.data.apiGatewayEndpoint
        )
        client = Client(config)

        # build request
        request = CommonParams(api_ver='1.0.4', language='en-US')
        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params=
            {
                "request":
                    {
                        "refreshToken": self._sessionByAuthCodeResponse.data.refreshToken,
                        "identityId": self._sessionByAuthCodeResponse.data.identityId
                    }
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/account/checkOrRefreshSession',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        # self._region = response.body.data
        # Decodifica il corpo della risposta
        response_body_str = response.body.decode('utf-8')

        # Carica la stringa JSON in un dizionario
        response_body_dict = json.loads(response_body_str)
            

    def list_binding_by_account(self):
        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=self._region.data.apiGatewayEndpoint
        )

        client = Client(config)

        # build request
        request = CommonParams(api_ver='1.0.8', language='en-US', iot_token=self._sessionByAuthCodeResponse.data.iotToken)
        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params=
            {
                "pageSize": 100,
                "pageNo": 1
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/uc/listBindingByAccount',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        # self._region = response.body.data
        # Decodifica il corpo della risposta
        response_body_str = response.body.decode('utf-8')

        # Carica la stringa JSON in un dizionario
        response_body_dict = json.loads(response_body_str)

        if int(response_body_dict.get('code')) != 200:
            raise Exception ('Error in creating session: ' + response_body_dict["msg"])
        else:
            self._listingDevByAccountResponse = ListingDevByAccountResponse.from_dict(response_body_dict)


    def send_cloud_command(self, command: bytes):
        config = Config(
            app_key=self._app_key,  # correct
            app_secret=self._app_secret,
            domain=self._region.data.apiGatewayEndpoint
        )

        client = Client(config)

        # build request
        request = CommonParams(api_ver='1.0.5', language='en-US', iot_token=self._sessionByAuthCodeResponse.data.iotToken)
        body = IoTApiRequest(
            id=str(uuid.uuid4()),
            params=
            {
                "args": {
                    "content":self.converter.printBase64Binary(command)
                },
                "identifier": "device_protobuf_sync_service",
                "iotId": "MbXcDE2X63CENA0lPGIo000000" # TODO get iotId from listbybinding request
            },
            request=request,
            version='1.0'
        )

        # send request
        # possibly need to do this ourselves
        response = client.do_request(
            '/thing/service/invoke',
            'https',
            'POST',
            None,
            body,
            RuntimeOptions()
        )
        print(response.status_message)
        print(response.headers)
        print(response.status_code)
        print(response.body)

        # self._region = response.body.data
        # Decodifica il corpo della risposta
        response_body_str = response.body.decode('utf-8')

        # Carica la stringa JSON in un dizionario
        response_body_dict = json.loads(response_body_str)

