import base64
import datetime
import itertools
import json
import queue
import sys
import time
import logging
from asyncio import sleep
from io import BytesIO
from typing import Dict, List

from bleak import BleakClient
from jsonic.serializable import serialize

from pyluba.aliyun.tmp_constant import tmp_constant
from pyluba.bluetooth.const import UUID_WRITE_CHARACTERISTIC
from pyluba.bluetooth.data.convert import parse_custom_data
from pyluba.bluetooth.data.framectrldata import FrameCtrlData
from pyluba.bluetooth.data.notifydata import BlufiNotifyData
from pyluba.data.model import Plan
from pyluba.data.model.execute_boarder import ExecuteBorder
from pyluba.mammotion.commands.messages.navigation import MessageNavigation
from pyluba.proto import (
    dev_net_pb2,
    luba_msg_pb2,
    mctrl_nav_pb2,
    mctrl_sys_pb2,
)
from pyluba.utility.constant.device_constant import bleOrderCmd
from pyluba.utility.device_type import DeviceType
from pyluba.utility.rocker_util import RockerControlUtil

_LOGGER = logging.getLogger(__name__)


class BleMessage:
    """Class for sending and recieving messages from Luba"""

    AES_TRANSFORMATION = "AES/CFB/NoPadding"
    DEFAULT_PACKAGE_LENGTH = 20
    DH_G = "2"
    DH_P = "cf5cf5c38419a724957ff5dd323b9c45c3cdd261eb740f69aa94b8bb1a5c96409153bd76b24222d03274e4725a5406092e9e82e9135c643cae98132b0d95f7d65347c68afc1e677da90e51bbab5f5cf429c291b4ba39c6b2dc5e8c7231e46aa7728e87664532cdf547be20c9a3fa8342be6e34371a27c06f7dc0edddd2f86373"
    MIN_PACKAGE_LENGTH = 20
    NEG_SECURITY_SET_ALL_DATA = 1
    NEG_SECURITY_SET_TOTAL_LENGTH = 0
    PACKAGE_HEADER_LENGTH = 4
    mPrintDebug = False
    mWriteTimeout = -1
    mPackageLengthLimit = -1
    mBlufiMTU = -1
    mEncrypted = False
    mChecksum = False
    mRequireAck = False
    mConnectState = 0
    mSendSequence: iter
    mReadSequence: iter
    mAck: queue
    notification: BlufiNotifyData
    messageNavigation:MessageNavigation = MessageNavigation()

    def __init__(self, client: BleakClient):
        self.client = client
        self.mSendSequence = itertools.count()
        self.mReadSequence = itertools.count()
        self.mAck = queue.Queue()
        self.notification = BlufiNotifyData()

    async def get_report_cfg(self, timeout: int, period: int, no_change_period: int):

        mctlsys = mctrl_sys_pb2.MctlSys(
            todev_report_cfg=mctrl_sys_pb2.report_info_cfg(
                timeout=timeout,
                period=period,
                no_change_period=no_change_period,
                count=1
            )
        )

        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_CONNECT
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_RTK
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_DEV_LOCAL
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_WORK
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_DEV_STA
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_VISION_POINT
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_VIO
        )
        mctlsys.todev_report_cfg.sub.append(
            mctrl_sys_pb2.rpt_info_type.RIT_VISION_STATISTIC
        )

        lubaMsg = luba_msg_pb2.LubaMsg()
        lubaMsg.msgtype = luba_msg_pb2.MSG_CMD_TYPE_EMBED_SYS
        lubaMsg.sender = luba_msg_pb2.DEV_MOBILEAPP
        lubaMsg.rcver = luba_msg_pb2.DEV_MAINCTL
        lubaMsg.msgattr = luba_msg_pb2.MSG_ATTR_REQ
        lubaMsg.seqs = 1
        lubaMsg.version = 1
        lubaMsg.subtype = 1
        lubaMsg.sys.CopyFrom(mctlsys)
        byte_arr = lubaMsg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def get_device_base_info(self):
        net = dev_net_pb2.DevNet(
            todev_devinfo_req=dev_net_pb2.DrvDevInfoReq()
        )
        net.todev_devinfo_req.req_ids.add(
            id=1,
            type=6
        )

        lubaMsg = luba_msg_pb2.LubaMsg()
        lubaMsg.msgtype = luba_msg_pb2.MSG_CMD_TYPE_ESP
        lubaMsg.sender = luba_msg_pb2.DEV_MOBILEAPP
        lubaMsg.msgattr = luba_msg_pb2.MSG_ATTR_REQ
        lubaMsg.seqs = 1
        lubaMsg.version = 1
        lubaMsg.subtype = 1
        lubaMsg.net.CopyFrom(net)
        byte_arr = lubaMsg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def get_device_version_main(self):
        commEsp = dev_net_pb2.DevNet(
            todev_devinfo_req=dev_net_pb2.DrvDevInfoReq()
        )

        for i in range(1, 8):
            if (i == 1):
                commEsp.todev_devinfo_req.req_ids.add(
                    id=i,
                    type=6
                )
            commEsp.todev_devinfo_req.req_ids.add(
                id=i,
                type=3
            )

        lubaMsg = luba_msg_pb2.LubaMsg()
        lubaMsg.msgtype = luba_msg_pb2.MSG_CMD_TYPE_ESP
        lubaMsg.sender = luba_msg_pb2.DEV_MOBILEAPP
        lubaMsg.msgattr = luba_msg_pb2.MSG_ATTR_REQ
        lubaMsg.seqs = 1
        lubaMsg.version = 1
        lubaMsg.subtype = 1
        lubaMsg.net.CopyFrom(commEsp)
        byte_arr = lubaMsg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def send_todev_ble_sync(self, sync_type: int):
        net = dev_net_pb2.DevNet(
            todev_ble_sync=sync_type
        )

        byte_arr = self.send_order_msg_net(net)
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def set_data_synchronization(self, type: int):
        mctrl_nav = mctrl_nav_pb2.MctlNav(
            todev_get_commondata=mctrl_nav_pb2.NavGetCommData(
                pver=1,
                action=12,
                type=type
            )
        )

        lubaMsg = luba_msg_pb2.LubaMsg()
        lubaMsg.msgtype = luba_msg_pb2.MSG_CMD_TYPE_NAV
        lubaMsg.sender = luba_msg_pb2.DEV_MAINCTL
        lubaMsg.rcver = luba_msg_pb2.MSG_ATTR_REQ
        lubaMsg.seqs = 1
        lubaMsg.version = 1
        lubaMsg.subtype = 1
        lubaMsg.nav.CopyFrom(mctrl_nav)
        byte_arr = lubaMsg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def get_task(self):
        hash_map = {"pver": 1, "subCmd": 2, "result": 0}
        await self.messageNavigation.post_custom_data(self.get_json_string(bleOrderCmd.task, hash_map))

    async def send_ble_alive(self):
        hash_map = {"ctrl": 1}
        await self.messageNavigation.post_custom_data(self.get_json_string(bleOrderCmd.bleAlive, hash_map))

    def clearNotification(self):
        self.notification = None
        self.notification = BlufiNotifyData()

    # async def get_device_info(self):
    #     await self.postCustomData(self.getJsonString(bleOrderCmd.getDeviceInfo))

    async def send_device_info(self):
        """Currently not called"""
        luba_msg = luba_msg_pb2.LubaMsg(
            msgtype=luba_msg_pb2.MsgCmdType.MSG_CMD_TYPE_ESP,
            sender=luba_msg_pb2.MsgDevice.DEV_MOBILEAPP,
            rcver=luba_msg_pb2.MsgDevice.DEV_COMM_ESP,
            msgattr=luba_msg_pb2.MsgAttr.MSG_ATTR_REQ,
            seqs=1,
            version=1,
            subtype=1,
            net=dev_net_pb2.DevNet(
                todev_ble_sync=1,
                todev_devinfo_req=dev_net_pb2.DrvDevInfoReq()
            )
        )
        byte_arr = luba_msg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(byte_arr)

    async def requestDeviceStatus(self):
        request = False
        type = self.messageNavigation.getTypeValue(0, 5)
        try:
            request = await self.messageNavigation.post(BleMessage.mEncrypted, BleMessage.mChecksum, False, type, None)
            # print(request)
        except Exception as err:
            # Log.w(TAG, "post requestDeviceStatus interrupted")
            request = False
            print(err)

        # if not request:
        #     onStatusResponse(BlufiCallback.CODE_WRITE_DATA_FAILED, null)

    async def requestDeviceVersion(self):
        request = False
        type = self.messageNavigation.getTypeValue(0, 7)
        try:
            request = await self.messageNavigation.post(BleMessage.mEncrypted, BleMessage.mChecksum, False, type, None)
            # print(request)
        except Exception as err:
            # Log.w(TAG, "post requestDeviceStatus interrupted")
            request = False
            print(err)

    async def setBladeControl(self, onOff: int):
        mctlsys = mctrl_sys_pb2.MctlSys()
        sysKnifeControl = mctrl_sys_pb2.SysKnifeControl()
        sysKnifeControl.knifeStatus = onOff
        mctlsys.todev_knife_ctrl.CopyFrom(sysKnifeControl)

        lubaMsg = luba_msg_pb2.LubaMsg()
        lubaMsg.msgtype = luba_msg_pb2.MSG_CMD_TYPE_EMBED_SYS
        lubaMsg.sender = luba_msg_pb2.DEV_MOBILEAPP
        lubaMsg.rcver = luba_msg_pb2.DEV_MAINCTL
        lubaMsg.msgattr = luba_msg_pb2.MSG_ATTR_REQ
        lubaMsg.seqs = 1
        lubaMsg.version = 1
        lubaMsg.subtype = 1
        lubaMsg.sys.CopyFrom(mctlsys)
        bytes = lubaMsg.SerializeToString()
        await self.messageNavigation.post_custom_data_bytes(bytes)

    async def start_job(self, blade_height):
        """Call after calling generate_route_information I think"""
        await self.set_knife_height(blade_height)
        await self.start_work_job()

    async def transformSpeed(self, linear: float, percent: float):

        transfrom3 = RockerControlUtil.getInstance().transfrom3(linear, percent)
        if (transfrom3 is not None and len(transfrom3) > 0):
            linearSpeed = transfrom3[0] * 10
            angularSpeed = (int)(transfrom3[1] * 4.5)

            await self.send_control(linearSpeed, angularSpeed)

    async def transformBothSpeeds(self, linear: float, angular: float, linearPercent: float, angularPercent: float):
        transfrom3 = RockerControlUtil.getInstance().transfrom3(linear, linearPercent)
        transform4 = RockerControlUtil.getInstance().transfrom3(angular, angularPercent)

        if (transfrom3 != None and len(transfrom3) > 0):
            linearSpeed = transfrom3[0] * 10
            angularSpeed = (int)(transform4[1] * 4.5)
            print(linearSpeed, angularSpeed)
            await self.send_control(linearSpeed, angularSpeed)

    # asnyc def transfromDoubleRockerSpeed(float f, float f2, boolean z):
    #         transfrom3 = RockerControlUtil.getInstance().transfrom3(f, f2)
    #         if (transfrom3 != null && transfrom3.size() > 0):
    #             if (z):
    #                 this.linearSpeed = transfrom3.get(0).intValue() * 10
    #             else
    #                 this.angularSpeed = (int) (transfrom3.get(1).intValue() * 4.5d)

    #         if (this.countDownTask == null):
    #             testSendControl()

    async def sendBorderPackage(self, executeBorder: ExecuteBorder):
        await self.messageNavigation.post_custom_data(serialize(executeBorder))

    async def gatt_write(self, data: bytes) -> None:
        await self.client.write_gatt_char(UUID_WRITE_CHARACTERISTIC, data, True)

    def parseNotification(self, response: bytearray):
        dataOffset = None
        if (response is None):
            # Log.w(TAG, "parseNotification null data");
            return -1

        # if (this.mPrintDebug):
        #     Log.d(TAG, "parseNotification Notification= " + Arrays.toString(response));
        # }
        if (len(response) >= 4):
            sequence = int(response[2])  # toInt
            if sequence != next(self.mReadSequence):
                print("parseNotification read sequence wrong",
                      sequence, self.mReadSequence)
                self.mReadSequence = itertools.count(start=sequence)
                # this is questionable
                # self.mReadSequence = sequence
                # self.mReadSequence_2.incrementAndGet()

            # LogUtil.m7773e(self.mGatt.getDevice().getName() + "打印丢包率", self.mReadSequence_2 + "/" + self.mReadSequence_1);
            pkt_type = int(response[0])  # toInt
            pkgType = self._getPackageType(pkt_type)
            subType = self._getSubType(pkt_type)
            self.notification.setType(pkt_type)
            self.notification.setPkgType(pkgType)
            self.notification.setSubType(subType)
            frameCtrl = int(response[1])  # toInt
            # print("frame ctrl")
            # print(frameCtrl)
            # print(response)
            # print(f"pktType {pkt_type} pkgType {pkgType} subType {subType}")
            self.notification.setFrameCtrl(frameCtrl)
            frameCtrlData = FrameCtrlData(frameCtrl)
            dataLen = int(response[3])  # toInt specifies length of data

            try:
                dataBytes = response[4: 4 + dataLen]
                if frameCtrlData.isEncrypted():
                    print("is encrypted")
                #     BlufiAES aes = new BlufiAES(self.mAESKey, AES_TRANSFORMATION, generateAESIV(sequence));
                #     dataBytes = aes.decrypt(dataBytes);
                # }
                if (frameCtrlData.isChecksum()):
                    print("checksum")
                #     int respChecksum1 = toInt(response[response.length - 1]);
                #     int respChecksum2 = toInt(response[response.length - 2]);
                #     int crc = BlufiCRC.calcCRC(BlufiCRC.calcCRC(0, new byte[]{(byte) sequence, (byte) dataLen}), dataBytes);
                #     int calcChecksum1 = (crc >> 8) & 255;
                #     int calcChecksum2 = crc & 255;
                #     if (respChecksum1 != calcChecksum1 || respChecksum2 != calcChecksum2) {
                #         Log.w(TAG, "parseNotification: read invalid checksum");
                #         if (self.mPrintDebug) {
                #             Log.d(TAG, "expect   checksum: " + respChecksum1 + ", " + respChecksum2);
                #             Log.d(TAG, "received checksum: " + calcChecksum1 + ", " + calcChecksum2);
                #             return -4;
                #         }
                #         return -4;
                #     }
                # }
                if (frameCtrlData.hasFrag()):
                    dataOffset = 2
                else:
                    dataOffset = 0

                self.notification.addData(dataBytes, dataOffset)
                return 1 if frameCtrlData.hasFrag() else 0
            except Exception as e:
                print(e)
                return -100

        # Log.w(TAG, "parseNotification data length less than 4");
        return -2

    async def parseBlufiNotifyData(self, return_bytes: bool = False):
        pkgType = self.notification.getPkgType()
        subType = self.notification.getSubType()
        dataBytes = self.notification.getDataArray()
        if (pkgType == 0):
            # never seem to get these..
            self._parseCtrlData(subType, dataBytes)
        if (pkgType == 1):
            if return_bytes:
                return dataBytes
            return await self._parseDataData(subType, dataBytes)

    def _parseCtrlData(self, subType: int, data: bytes):
        pass
        # self._parseAck(data)

    async def _parseDataData(self, subType: int, data: bytes):
        #     if (subType == 0) {
        #         this.mSecurityCallback.onReceiveDevicePublicKey(data);
        #         return;
        #     }
        print(subType)
        match subType:
            #         case 15:
            #             parseWifiState(data);
            #             return;
            #         case 16:
            #             parseVersion(data);
            #             return;
            #         case 17:
            #             parseWifiScanList(data);
            #             return;
            #         case 18:
            #             int errCode = data.length > 0 ? 255 & data[0] : 255;
            #             onError(errCode);
            #             return;
            case 19:
                #             # com/agilexrobotics/utils/EspBleUtil$BlufiCallbackMain.smali
                luba_msg = parse_custom_data(data)  # parse to protobuf message
                # really need some sort of callback
                if luba_msg.HasField('net'):
                    if luba_msg.net.HasField('toapp_wifi_iot_status'):
                        # await sleep(1.5)
                        await self.send_todev_ble_sync(2)
                return luba_msg

    # private void parseCtrlData(int i, byte[] bArr) {
    #     if (i == 0) {
    #         parseAck(bArr);
    #     }
    # }

    # private void parseAck(byte[] bArr) {
    #     this.mAck.add(Integer.valueOf(bArr.length > 0 ? bArr[0] & 255 : 256));
    # }

    def getJsonString(self, cmd: int) -> str:
        jSONObject = {}
        try:
            jSONObject["cmd"] = cmd
            jSONObject[tmp_constant.REQUEST_ID] = int(time.time())
            return json.dumps(jSONObject)
        except Exception:

            return ""

    def current_milli_time(self):
        return round(time.time() * 1000)

    def _getPackageType(self, typeValue: int):
        return typeValue & 3

    def _getSubType(self, typeValue: int):
        return (typeValue & 252) >> 2
