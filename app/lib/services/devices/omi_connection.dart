import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:awesome_notifications/awesome_notifications.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:omi/backend/schema/bt_device/bt_device.dart';
import 'package:omi/services/devices.dart';
import 'package:omi/services/devices/device_connection.dart';
import 'package:omi/services/devices/errors.dart';
import 'package:omi/services/devices/models.dart';
import 'package:omi/utils/audio/wav_bytes.dart';
import 'package:omi/utils/logger.dart';

class OmiDeviceConnection extends DeviceConnection {
  BluetoothService? _batteryService;
  BluetoothService? _omiService;
  BluetoothService? _storageService;
  BluetoothService? _accelService;
  BluetoothService? _buttonService;
  BluetoothService? _speakerService;
  BluetoothService? _hapticService;

  OmiDeviceConnection(super.device, super.bleDevice);

  get deviceId => device.id;

  @override
  Future<void> connect(
      {Function(String deviceId, DeviceConnectionState state)?
          onConnectionStateChanged}) async {
    await super.connect(onConnectionStateChanged: onConnectionStateChanged);

    // Debug: List all discovered services
    print('🔍 DEBUG: === DISCOVERED SERVICES ===');
    try {
      var services = await bleDevice.discoverServices();
      print('🔍 DEBUG: Found ${services.length} total services:');
      for (var service in services) {
        var uuid = service.uuid.str128.toLowerCase();
        print('🔍 DEBUG: Service UUID: $uuid');
        print(
            '🔍 DEBUG: Service characteristics: ${service.characteristics.length}');
      }
    } catch (e) {
      print('❌ DEBUG: Error listing services: $e');
    }
    print('🔍 DEBUG: === END SERVICES LIST ===');

    // Services
    print('🔍 DEBUG: Looking for omiServiceUuid: $omiServiceUuid');
    _omiService = await getService(omiServiceUuid);
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      throw DeviceConnectionException("Omi ble service is not found");
    } else {
      print('🟢 DEBUG: Found Omi service');
    }

    print('🔍 DEBUG: Looking for batteryServiceUuid: $batteryServiceUuid');
    _batteryService = await getService(batteryServiceUuid);
    if (_batteryService == null) {
      logServiceNotFoundError('Battery', deviceId);
    } else {
      print('🟢 DEBUG: Found Battery service');
    }

    print(
        '🔍 DEBUG: Looking for storageDataStreamServiceUuid: $storageDataStreamServiceUuid');
    _storageService = await getService(storageDataStreamServiceUuid);
    if (_storageService == null) {
      logServiceNotFoundError('Storage', deviceId);
    } else {
      print('🟢 DEBUG: Found Storage service');
    }

    print(
        '🔍 DEBUG: Looking for speakerDataStreamServiceUuid: $speakerDataStreamServiceUuid');
    _speakerService = await getService(speakerDataStreamServiceUuid);
    if (_speakerService == null) {
      logServiceNotFoundError('Speaker', deviceId);
    } else {
      print('🟢 DEBUG: Found Speaker service');
    }

    print(
        '🔍 DEBUG: Looking for accelDataStreamServiceUuid: $accelDataStreamServiceUuid');
    _accelService = await getService(accelDataStreamServiceUuid);
    if (_accelService == null) {
      logServiceNotFoundError('Accelerometer', deviceId);
    } else {
      print('🟢 DEBUG: Found Accelerometer service');
    }

    print('🔍 DEBUG: Looking for buttonServiceUuid: $buttonServiceUuid');
    _buttonService = await getService(buttonServiceUuid);
    if (_buttonService == null) {
      logServiceNotFoundError('Button', deviceId);
    } else {
      print('🟢 DEBUG: Found Button service');
    }

    // Try to get dedicated Haptic service (main OMI firmware)
    print('🔍 DEBUG: Looking for hapticServiceUuid: $hapticServiceUuid');
    _hapticService = await getService(hapticServiceUuid);
    if (_hapticService == null) {
      logServiceNotFoundError('Haptic', deviceId);
    } else {
      print('🟢 DEBUG: Found Haptic service');
    }
  }

  // Mimic @app/lib/utils/ble/friend_communication.dart
  @override
  Future<bool> isConnected() async {
    return bleDevice.isConnected;
  }

  @override
  Future<int> performRetrieveBatteryLevel() async {
    if (_batteryService == null) {
      logServiceNotFoundError('Battery', deviceId);
      return -1;
    }

    var batteryLevelCharacteristic =
        getCharacteristic(_batteryService!, batteryLevelCharacteristicUuid);
    if (batteryLevelCharacteristic == null) {
      logCharacteristicNotFoundError('Battery level', deviceId);
      return -1;
    }

    var currValue = await batteryLevelCharacteristic.read();
    if (currValue.isNotEmpty) return currValue[0];
    return -1;
  }

  @override
  Future<StreamSubscription<List<int>>?> performGetBleBatteryLevelListener({
    void Function(int)? onBatteryLevelChange,
  }) async {
    if (_batteryService == null) {
      logServiceNotFoundError('Battery', deviceId);
      return null;
    }

    var batteryLevelCharacteristic =
        getCharacteristic(_batteryService!, batteryLevelCharacteristicUuid);
    if (batteryLevelCharacteristic == null) {
      logCharacteristicNotFoundError('Battery level', deviceId);
      return null;
    }

    var currValue = await batteryLevelCharacteristic.read();
    if (currValue.isNotEmpty) {
      debugPrint('Battery level: ${currValue[0]}');
      onBatteryLevelChange!(currValue[0]);
    }

    try {
      await batteryLevelCharacteristic.setNotifyValue(true);
    } catch (e, stackTrace) {
      logSubscribeError('Battery level', deviceId, e, stackTrace);
      return null;
    }

    var listener = batteryLevelCharacteristic.lastValueStream.listen((value) {
      // debugPrint('Battery level listener: $value');
      if (value.isNotEmpty) {
        debugPrint('Battery level changed: ${value[0]}');
        onBatteryLevelChange!(value[0]);
      }
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    return listener;
  }

  @override
  Future<List<int>> performGetButtonState() async {
    debugPrint('perform button state called');
    if (_buttonService == null) {
      return Future.value(<int>[]);
    }

    var buttonStateCharacteristic =
        getCharacteristic(_buttonService!, buttonTriggerCharacteristicUuid);
    if (buttonStateCharacteristic == null) {
      logCharacteristicNotFoundError('Button state', deviceId);
      return Future.value(<int>[]);
    }
    var value = await buttonStateCharacteristic.read();
    return value;
  }

  @override
  Future<StreamSubscription?> performGetBleButtonListener({
    required void Function(List<int>) onButtonReceived,
  }) async {
    if (_buttonService == null) {
      logServiceNotFoundError('Button', deviceId);
      return null;
    }

    var buttonDataStreamCharacteristic =
        getCharacteristic(_buttonService!, buttonTriggerCharacteristicUuid);
    if (buttonDataStreamCharacteristic == null) {
      logCharacteristicNotFoundError('Button data stream', deviceId);
      return null;
    }

    try {
      // TODO: Unknown GATT error here (code 133) on Android. StackOverflow says that it has to do with smaller MTU size
      // The creator of the plugin says not to use autoConnect
      // https://github.com/chipweinberger/flutter_blue_plus/issues/612
      final device = bleDevice;
      if (device.isConnected) {
        if (Platform.isAndroid && device.mtuNow < 512) {
          await device.requestMtu(512); // This might fix the code 133 error
        }
        if (device.isConnected) {
          try {
            await buttonDataStreamCharacteristic
                .setNotifyValue(true); // device could be disconnected here.
          } on PlatformException catch (e) {
            Logger.error('Error setting notify value for audio data stream $e');
          }
        } else {
          Logger.handle(
              Exception('Device disconnected before setting notify value'),
              StackTrace.current,
              message:
                  'Device is disconnected. Please reconnect and try again');
        }
      }
    } catch (e, stackTrace) {
      logSubscribeError('Button data stream', deviceId, e, stackTrace);
      return null;
    }

    debugPrint('Subscribed to button stream from Omi Device');
    var listener =
        buttonDataStreamCharacteristic.lastValueStream.listen((value) {
      debugPrint("new button value ${value}");
      if (value.isNotEmpty) onButtonReceived(value);
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    // This will cause a crash in OpenGlass devices
    // due to a race with discoverServices() that triggers
    // a bug in the device firmware.
    if (Platform.isAndroid && device.isConnected) await device.requestMtu(512);

    return listener;
  }

  @override
  Future<StreamSubscription?> performGetBleAudioBytesListener({
    required void Function(List<int>) onAudioBytesReceived,
  }) async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return null;
    }

    var audioDataStreamCharacteristic =
        getCharacteristic(_omiService!, audioDataStreamCharacteristicUuid);
    if (audioDataStreamCharacteristic == null) {
      logCharacteristicNotFoundError('Audio data stream', deviceId);
      return null;
    }

    try {
      // TODO: Unknown GATT error here (code 133) on Android. StackOverflow says that it has to do with smaller MTU size
      // The creator of the plugin says not to use autoConnect
      // https://github.com/chipweinberger/flutter_blue_plus/issues/612
      final device = bleDevice;
      if (device.isConnected) {
        if (Platform.isAndroid && device.mtuNow < 512) {
          await device.requestMtu(512); // This might fix the code 133 error
        }
        if (device.isConnected) {
          try {
            await audioDataStreamCharacteristic
                .setNotifyValue(true); // device could be disconnected here.
          } on PlatformException catch (e) {
            Logger.error('Error setting notify value for audio data stream $e');
          }
        } else {
          Logger.handle(
              Exception('Device disconnected before setting notify value'),
              StackTrace.current,
              message:
                  'Device is disconnected. Please reconnect and try again');
        }
      }
    } catch (e, stackTrace) {
      logSubscribeError('Audio data stream', deviceId, e, stackTrace);
      return null;
    }

    debugPrint('Subscribed to audioBytes stream from Omi Device');
    var listener =
        audioDataStreamCharacteristic.lastValueStream.listen((value) {
      if (value.isNotEmpty) onAudioBytesReceived(value);
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    // This will cause a crash in OpenGlass devices
    // due to a race with discoverServices() that triggers
    // a bug in the device firmware.
    if (Platform.isAndroid && device.isConnected) await device.requestMtu(512);

    return listener;
  }

  @override
  Future<BleAudioCodec> performGetAudioCodec() async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return BleAudioCodec.pcm8;
    }

    var audioCodecCharacteristic =
        getCharacteristic(_omiService!, audioCodecCharacteristicUuid);
    if (audioCodecCharacteristic == null) {
      logCharacteristicNotFoundError('Audio codec', deviceId);
      return BleAudioCodec.pcm8;
    }

    // Default codec is PCM8
    var codecId = 1;
    BleAudioCodec codec = BleAudioCodec.pcm8;

    var codecValue = await audioCodecCharacteristic.read();
    if (codecValue.isNotEmpty) {
      codecId = codecValue[0];
    }

    switch (codecId) {
      // case 0:
      //   codec = BleAudioCodec.pcm16;
      case 1:
        codec = BleAudioCodec.pcm8;
      // case 10:
      //   codec = BleAudioCodec.mulaw16;
      // case 11:
      //   codec = BleAudioCodec.mulaw8;
      case 20:
        codec = BleAudioCodec.opus;
      case 21:
        codec = BleAudioCodec.opusFS320;
      default:
        logErrorMessage('Unknown codec id: $codecId', deviceId);
    }

    // debugPrint('Codec is $codec');
    return codec;
  }

  @override
  Future<List<int>> getStorageList() async {
    if (await isConnected()) {
      debugPrint('storage list called');
      return await performGetStorageList();
    }
    // _showDeviceDisconnectedNotification();
    debugPrint('storage list error');
    return Future.value(<int>[]);
  }

  @override
  Future<List<int>> performGetStorageList() async {
    debugPrint(' perform storage list called');
    if (_storageService == null) {
      if (device.name == 'Omi DevKit 2') {
        // Should only report incase of DevKit 2 because only DevKit 2 has storage service
        logServiceNotFoundError('Storage', deviceId);
      }
      return Future.value(<int>[]);
    }

    var storageListCharacteristic = getCharacteristic(
        _storageService!, storageReadControlCharacteristicUuid);
    if (storageListCharacteristic == null) {
      logCharacteristicNotFoundError('Storage List', deviceId);
      return Future.value(<int>[]);
    }

    List<int> storageValue;
    try {
      storageValue = await storageListCharacteristic.read();
    } catch (e, stackTrace) {
      logCrashMessage('Storage value', deviceId, e, stackTrace);
      return Future.value(<int>[]);
    }
    List<int> storageLengths = [];
    if (storageValue.isNotEmpty) {
      int totalEntries = (storageValue.length / 4).toInt();
      debugPrint('Storage list: ${totalEntries} items');

      for (int i = 0; i < totalEntries; i++) {
        int baseIndex = i * 4;
        var result = ((storageValue[baseIndex] |
                    (storageValue[baseIndex + 1] << 8) |
                    (storageValue[baseIndex + 2] << 16) |
                    (storageValue[baseIndex + 3] << 24)) &
                0xFFFFFFFF as int)
            .toSigned(32);
        storageLengths.add(result);
      }
    }
    debugPrint('storage list finished');
    debugPrint(
        'Storage lengths: ${storageLengths.length} items: ${storageLengths.join(', ')}');
    return storageLengths;
  }

  @override
  Future<StreamSubscription?> performGetBleStorageBytesListener({
    required void Function(List<int>) onStorageBytesReceived,
  }) async {
    if (_storageService == null) {
      logServiceNotFoundError('Storage Write', deviceId);
      return null;
    }

    var storageDataStreamCharacteristic = getCharacteristic(
        _storageService!, storageDataStreamCharacteristicUuid);
    if (storageDataStreamCharacteristic == null) {
      logCharacteristicNotFoundError('Storage data stream', deviceId);
      return null;
    }

    try {
      await storageDataStreamCharacteristic
          .setNotifyValue(true); // device could be disconnected here.
    } catch (e, stackTrace) {
      logSubscribeError('Storage data stream', deviceId, e, stackTrace);
      return null;
    }

    debugPrint('Subscribed to StorageBytes stream from Omi Device');
    var listener =
        storageDataStreamCharacteristic.lastValueStream.listen((value) {
      if (value.isNotEmpty) onStorageBytesReceived(value);
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    // await storageDataStreamCharacteristic.write([0x00,0x01]);

    // This will cause a crash in OpenGlass devices
    // due to a race with discoverServices() that triggers
    // a bug in the device firmware.
    if (Platform.isAndroid) await device.requestMtu(512);

    return listener;
  }

  // level
  //   1 - play 100ms (main OMI firmware) / 20ms (devkit firmware)
  //   2 - play 300ms (main OMI firmware) / 50ms (devkit firmware)
  //   3 - play 500ms (both firmwares)
  @override
  Future<bool> performPlayToSpeakerHaptic(int level) async {
    // Try dedicated Haptic service first (main OMI firmware)
    if (_hapticService != null) {
      var hapticCharacteristic =
          getCharacteristic(_hapticService!, hapticCharacteristicUuid);
      if (hapticCharacteristic != null) {
        debugPrint('🎯 HAPTIC: Using dedicated Haptic service (level $level)');
        await hapticCharacteristic.write([level & 0xFF]);
        return true;
      }
    }

    // Fallback to Speaker service (devkit firmware)
    if (_speakerService != null) {
      var speakerDataStreamCharacteristic = getCharacteristic(
          _speakerService!, speakerDataStreamCharacteristicUuid);
      if (speakerDataStreamCharacteristic != null) {
        debugPrint('🎯 HAPTIC: Using Speaker service fallback (level $level)');
        await speakerDataStreamCharacteristic.write([level & 0xFF]);
        return true;
      }
    }

    // No haptic service available
    logServiceNotFoundError('Haptic/Speaker', deviceId);
    return false;
  }

  @override
  Future<bool> performWriteToStorage(
      int numFile, int command, int offset) async {
    if (_storageService == null) {
      logServiceNotFoundError('Storage Write', deviceId);
      return false;
    }

    var storageDataStreamCharacteristic = getCharacteristic(
        _storageService!, storageDataStreamCharacteristicUuid);
    if (storageDataStreamCharacteristic == null) {
      logCharacteristicNotFoundError('Storage data stream', deviceId);
      return false;
    }
    debugPrint('About to write to storage bytes');
    debugPrint('about to send $numFile');
    debugPrint('about to send $command');
    debugPrint('about to send offset$offset');
    var offsetBytes = [
      (offset >> 24) & 0xFF,
      (offset >> 16) & 0xFF,
      (offset >> 8) & 0xFF,
      offset & 0xFF,
    ];

    await storageDataStreamCharacteristic.write([
      command & 0xFF,
      numFile & 0xFF,
      offsetBytes[0],
      offsetBytes[1],
      offsetBytes[2],
      offsetBytes[3]
    ]);
    return true;
  }
  // Future<List<int>> performGetStorageList();

  @override
  Future performCameraStartPhotoController() async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return;
    }

    var imageCaptureControlCharacteristic =
        getCharacteristic(_omiService!, imageCaptureControlCharacteristicUuid);
    if (imageCaptureControlCharacteristic == null) {
      logCharacteristicNotFoundError('Image capture control', deviceId);
      return;
    }

    // Capture photo once every 10s
    await imageCaptureControlCharacteristic.write([0x0A]);

    print('cameraStartPhotoController');
  }

  @override
  Future performCameraStopPhotoController() async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return;
    }

    var imageCaptureControlCharacteristic =
        getCharacteristic(_omiService!, imageCaptureControlCharacteristicUuid);
    if (imageCaptureControlCharacteristic == null) {
      logCharacteristicNotFoundError('Image capture control', deviceId);
      return;
    }

    await imageCaptureControlCharacteristic.write([0x00]);

    print('cameraStopPhotoController');
  }

  @override
  Future<bool> performHasPhotoStreamingCharacteristic() async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return false;
    }
    var imageCaptureControlCharacteristic =
        getCharacteristic(_omiService!, imageDataStreamCharacteristicUuid);
    return imageCaptureControlCharacteristic != null;
  }

  Future<StreamSubscription?> _getBleImageBytesListener({
    required void Function(List<int>) onImageBytesReceived,
  }) async {
    if (_omiService == null) {
      logServiceNotFoundError('Omi', deviceId);
      return null;
    }

    var imageStreamCharacteristic =
        getCharacteristic(_omiService!, imageDataStreamCharacteristicUuid);
    if (imageStreamCharacteristic == null) {
      logCharacteristicNotFoundError('Image data stream', deviceId);
      return null;
    }

    try {
      await imageStreamCharacteristic
          .setNotifyValue(true); // device could be disconnected here.
    } catch (e, stackTrace) {
      logSubscribeError('Image data stream', deviceId, e, stackTrace);
      return null;
    }

    debugPrint('Subscribed to imageBytes stream from Omi Device');
    var listener = imageStreamCharacteristic.lastValueStream.listen((value) {
      if (value.isNotEmpty) onImageBytesReceived(value);
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    // This will cause a crash in OpenGlass devices
    // due to a race with discoverServices() that triggers
    // a bug in the device firmware.
    // if (Platform.isAndroid) await device.requestMtu(512);

    return listener;
  }

  @override
  Future<StreamSubscription?> performGetImageListener({
    required void Function(Uint8List base64JpgData) onImageReceived,
  }) async {
    if (!await hasPhotoStreamingCharacteristic()) {
      return null;
    }
    print("OpenGlassDevice getImageListener called");
    ImageBytesUtil imageBytesUtil = ImageBytesUtil();
    var bleBytesStream = await _getBleImageBytesListener(
      onImageBytesReceived: (List<int> value) async {
        if (value.isEmpty) return;
        Uint8List data = Uint8List.fromList(value);
        // print(data);
        Uint8List? completedImage = imageBytesUtil.processChunk(data);
        if (completedImage != null && completedImage.isNotEmpty) {
          debugPrint('Completed image bytes length: ${completedImage.length}');
          onImageReceived(completedImage);
        }
      },
    );
    bleBytesStream?.onDone(() {
      debugPrint('Image listener done');
      cameraStopPhotoController();
    });
    return bleBytesStream;
  }

  @override
  Future<StreamSubscription<List<int>>?> performGetAccelListener({
    void Function(int)? onAccelChange,
  }) async {
    if (_accelService == null) {
      logServiceNotFoundError('Accelerometer', deviceId);
      return null;
    }

    var accelCharacteristic =
        getCharacteristic(_accelService!, accelDataStreamCharacteristicUuid);
    if (accelCharacteristic == null) {
      logCharacteristicNotFoundError('Accelerometer', deviceId);
      return null;
    }

    var currValue = await accelCharacteristic.read();
    if (currValue.isNotEmpty) {
      debugPrint('Accelerometer level: ${currValue[0]}');
      onAccelChange!(currValue[0]);
    }

    try {
      await accelCharacteristic.setNotifyValue(true);
    } catch (e, stackTrace) {
      logSubscribeError('Accelerometer level', deviceId, e, stackTrace);
      return null;
    }

    var listener = accelCharacteristic.lastValueStream.listen((value) {
      // debugPrint('Battery level listener: $value');

      if (value.length > 4) {
        //for some reason, the very first reading is four bytes

        if (value.isNotEmpty) {
          List<double> accelerometerData = [];
          onAccelChange!(value[0]);

          for (int i = 0; i < 6; i++) {
            int baseIndex = i * 8;
            var result = ((value[baseIndex] |
                        (value[baseIndex + 1] << 8) |
                        (value[baseIndex + 2] << 16) |
                        (value[baseIndex + 3] << 24)) &
                    0xFFFFFFFF as int)
                .toSigned(32);
            var temp = ((value[baseIndex + 4] |
                        (value[baseIndex + 5] << 8) |
                        (value[baseIndex + 6] << 16) |
                        (value[baseIndex + 7] << 24)) &
                    0xFFFFFFFF as int)
                .toSigned(32);
            double axisValue = result + (temp / 1000000);
            accelerometerData.add(axisValue);
          }
          debugPrint('Accelerometer x direction: ${accelerometerData[0]}');
          debugPrint('Gyroscope x direction: ${accelerometerData[3]}\n');

          debugPrint('Accelerometer y direction: ${accelerometerData[1]}');
          debugPrint('Gyroscope y direction: ${accelerometerData[4]}\n');

          debugPrint('Accelerometer z direction: ${accelerometerData[2]}');
          debugPrint('Gyroscope z direction: ${accelerometerData[5]}\n');
          //simple threshold fall calcaultor
          var fall_number = sqrt(pow(accelerometerData[0], 2) +
              pow(accelerometerData[1], 2) +
              pow(accelerometerData[2], 2));
          if (fall_number > 30.0) {
            AwesomeNotifications().createNotification(
              content: NotificationContent(
                id: 6,
                channelKey: 'channel',
                actionType: ActionType.Default,
                title: 'ouch',
                body: 'did you fall?',
                wakeUpScreen: true,
              ),
            );
          }
        }
      }
    });

    final device = bleDevice;
    device.cancelWhenDisconnected(listener);

    return listener;
  }
}
