import 'package:flutter/material.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/bt_device/bt_device.dart';
import 'package:omi/providers/device_provider.dart';
import 'package:omi/services/services.dart';
import 'package:omi/utils/analytics/intercom.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:omi/widgets/device_widget.dart';
import 'package:gradient_borders/box_borders/gradient_box_border.dart';
import 'package:provider/provider.dart';

import '../settings/device_settings.dart';

class ConnectedDevice extends StatefulWidget {
  const ConnectedDevice({super.key});

  @override
  State<ConnectedDevice> createState() => _ConnectedDeviceState();
}

class _ConnectedDeviceState extends State<ConnectedDevice> {
  // TODO: thinh, use connection directly
  Future _bleDisconnectDevice(BtDevice btDevice) async {
    var connection = await ServiceManager.instance().device.ensureConnection(btDevice.id);
    if (connection == null) {
      return Future.value(null);
    }
    return await connection.disconnect();
  }

  @override
  void initState() {
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await context.read<DeviceProvider>().getDeviceInfo();
    });
    super.initState();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceProvider>(builder: (context, provider, child) {
      return Scaffold(
        backgroundColor: Theme.of(context).colorScheme.primary,
        appBar: AppBar(
          title: Text(provider.connectedDevice != null ? 'Connected Device' : 'Paired Device'),
          backgroundColor: Theme.of(context).colorScheme.primary,
          actions: [
            IconButton(
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (context) => const DeviceSettings(),
                  ),
                );
              },
              icon: const Icon(Icons.settings),
            )
          ],
        ),
        body: Column(
          children: [
            const SizedBox(height: 32),
            const DeviceAnimationWidget(),
            Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              mainAxisAlignment: MainAxisAlignment.start,
              children: [
                Text(
                  '${provider.pairedDevice?.name} (${provider.pairedDevice?.getShortId() ?? SharedPreferencesUtil().btDevice.getShortId()})',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16.0,
                    fontWeight: FontWeight.w500,
                    height: 1.5,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 12),
                provider.pairedDevice != null && provider.pairedDevice?.modelNumber != "Unknown"
                    ? Column(
                        children: [
                          Text(
                            '${provider.pairedDevice?.modelNumber}, firmware ${provider.pairedDevice?.firmwareRevision}',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 10.0,
                              fontWeight: FontWeight.w500,
                              height: 1,
                            ),
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 12),
                          Text(
                            'by ${provider.pairedDevice?.manufacturerName}',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 10.0,
                              fontWeight: FontWeight.w500,
                              height: 1,
                            ),
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 12),
                        ],
                      )
                    : const SizedBox.shrink(),
                provider.connectedDevice != null
                    ? Container(
                        decoration: BoxDecoration(
                          color: Colors.transparent,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 10,
                              height: 10,
                              decoration: BoxDecoration(
                                color: provider.batteryLevel > 75
                                    ? const Color.fromARGB(255, 0, 255, 8)
                                    : provider.batteryLevel > 20
                                        ? Colors.yellow.shade700
                                        : Colors.red,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 8.0),
                            Text(
                              '${provider.batteryLevel.toString()}% Battery',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 14,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ],
                        ))
                    : const Text(
                        "Offline",
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      )
              ],
            ),
            const SizedBox(height: 32),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 0),
              decoration: BoxDecoration(
                border: const GradientBoxBorder(
                  gradient: LinearGradient(colors: [
                    Color.fromARGB(127, 208, 208, 208),
                    Color.fromARGB(127, 188, 99, 121),
                    Color.fromARGB(127, 86, 101, 182),
                    Color.fromARGB(127, 126, 190, 236)
                  ]),
                  width: 2,
                ),
                borderRadius: BorderRadius.circular(12),
              ),
              child: TextButton(
                onPressed: () async {
                  await SharedPreferencesUtil().btDeviceSet(BtDevice(id: '', name: '', type: DeviceType.omi, rssi: 0));
                  SharedPreferencesUtil().deviceName = '';
                  if (provider.connectedDevice != null) {
                    await _bleDisconnectDevice(provider.connectedDevice!);
                  }
                  context.read<DeviceProvider>().setIsConnected(false);
                  context.read<DeviceProvider>().setConnectedDevice(null);
                  context.read<DeviceProvider>().updateConnectingStatus(false);
                  Navigator.of(context).pop();
                  MixpanelManager().disconnectFriendClicked();
                },
                child: Text(
                  provider.connectedDevice == null ? "Unpair" : "Disconnect",
                  style: const TextStyle(color: Colors.white, fontSize: 16),
                ),
              ),
            ),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () async {
                await IntercomManager.instance.displayChargingArticle(provider.pairedDevice?.name ?? 'DevKit1');
              },
              child: const Text(
                'Issues charging?',
                style: TextStyle(
                  color: Colors.white,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
          ],
        ),
      );
    });
  }
}
