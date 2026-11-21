package com.microduck.console_apk

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHidDevice
import android.bluetooth.BluetoothHidDeviceAppSdpSettings
import android.bluetooth.BluetoothProfile
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import io.flutter.plugin.common.EventChannel
import java.util.concurrent.Executors

/**
 * Bluetooth classic HID gamepad named like a GameSir-Nova 2 Lite.
 * Report ID 1, then the nine bytes built in Dart:
 * buttons 1-8, buttons 9-15, hat, X, Y, Z (RT), Rx, Ry, Rz (LT).
 * Button 15 is the right-stick click. The report stays nine bytes: 15 button
 * bits plus one pad bit, then the same hat and axes.
 *
 * The descriptor is the Linux gamepad layout described in lib/hid_report.dart.
 */
class HidGamepad(private val activity: Activity) : EventChannel.StreamHandler {
    private val executor = Executors.newSingleThreadExecutor()
    private var adapter: BluetoothAdapter? = null
    private var hid: BluetoothHidDevice? = null
    private var host: BluetoothDevice? = null
    private var sink: EventChannel.EventSink? = null
    private var pendingResult: io.flutter.plugin.common.MethodChannel.Result? = null
    private var registered = false
    private var wantActive = false
    private var discoverableAccepted = false
    private var registering = false
    private var registerGeneration = 0
    private var previousName: String? = null
    private var report = byteArrayOf(0, 0, 15, 0, 0, 0x81.toByte(), 0, 0, 0x81.toByte())

    fun start(result: io.flutter.plugin.common.MethodChannel.Result) {
        val radio = BluetoothAdapter.getDefaultAdapter()
        adapter = radio
        if (radio == null) {
            result.error("no-bluetooth", "这台手机没有蓝牙", null)
            return
        }
        if (!radio.isEnabled) {
            result.error("bluetooth-off", "请先打开手机蓝牙", null)
            return
        }
        if (registered) {
            result.success(null)
            return
        }
        wantActive = true
        pendingResult = result
        if (Build.VERSION.SDK_INT >= 31) {
            val missing = listOf(
                android.Manifest.permission.BLUETOOTH_CONNECT,
                android.Manifest.permission.BLUETOOTH_ADVERTISE,
            ).filter {
                activity.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
            }
            if (missing.isNotEmpty()) {
                activity.requestPermissions(missing.toTypedArray(), REQUEST_PERMISSION)
                return
            }
        }
        continueStart()
    }

    fun onPermissions(granted: Boolean) {
        if (!wantActive) return
        if (!granted) {
            wantActive = false
            replyError("permission", "需要蓝牙连接和可被发现权限，才能让鸭子配对")
            return
        }
        continueStart()
    }

    /** Called when this activity is in front again. Leaving the screen unregisters HID. */
    fun onHostResume() {
        if (wantActive && discoverableAccepted && !registered && !registering) register()
    }

    fun stop() {
        wantActive = false
        discoverableAccepted = false
        registering = false
        registerGeneration++
        replySuccess()
        val device = hid
        val peer = host
        if (device != null && peer != null) {
            try {
                device.disconnect(peer)
            } catch (_: SecurityException) {
            }
        }
        if (device != null) {
            try {
                device.unregisterApp()
            } catch (_: SecurityException) {
            }
        }
        registered = false
        host = null
        adapter?.let { radio ->
            previousName?.let { name ->
                try {
                    radio.name = name
                } catch (_: SecurityException) {
                }
            }
        }
        previousName = null
        if (device != null) {
            adapter?.closeProfileProxy(BluetoothProfile.HID_DEVICE, device)
        }
        hid = null
        emit("stopped", null)
    }

    fun send(bytes: ByteArray) {
        if (bytes.size != REPORT_LENGTH) return
        report = bytes.copyOf()
        val device = hid ?: return
        val peer = host ?: return
        try {
            device.sendReport(peer, REPORT_ID, report)
        } catch (error: SecurityException) {
            emit("error", error.message)
        }
    }

    fun onDiscoverableResult(resultCode: Int) {
        if (!wantActive) return
        if (resultCode == Activity.RESULT_CANCELED) {
            wantActive = false
            discoverableAccepted = false
            replyError("discoverable", "手机没有进入可被发现状态，鸭子搜不到这台手柄")
            emit("error", "手机没有进入可被发现状态，鸭子搜不到这台手柄")
            return
        }
        discoverableAccepted = true
        register()
    }

    @SuppressLint("MissingPermission")
    private fun continueStart() {
        ensureGamepadName()
        val radio = adapter ?: return
        val alreadyVisible = try {
            radio.scanMode == BluetoothAdapter.SCAN_MODE_CONNECTABLE_DISCOVERABLE
        } catch (_: SecurityException) {
            false
        }
        if (alreadyVisible) {
            discoverableAccepted = true
            register()
            return
        }
        requestDiscoverable()
    }

    @SuppressLint("MissingPermission")
    private fun ensureGamepadName() {
        val radio = adapter ?: return
        val current = radio.name ?: return
        if (current == PAD_NAME) return
        if (previousName == null) previousName = current
        try {
            radio.name = PAD_NAME
        } catch (error: SecurityException) {
            Log.w(TAG, "cannot rename adapter", error)
        }
    }

    @SuppressLint("MissingPermission")
    private fun register() {
        if (!wantActive || !discoverableAccepted || registered || registering) return
        val radio = adapter ?: return
        registering = true
        val generation = ++registerGeneration
        activity.window.decorView.postDelayed({
            if (generation == registerGeneration && wantActive && !registered) {
                registering = false
                wantActive = false
                replyError("hid", "蓝牙 HID 服务没有响应")
                emit("error", "蓝牙 HID 服务没有响应")
            }
        }, 8000)
        val device = hid
        if (device != null) {
            submitRegistration(device)
            return
        }
        val opened = radio.getProfileProxy(activity, object : BluetoothProfile.ServiceListener {
            override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                activity.runOnUiThread {
                    val connected = proxy as BluetoothHidDevice
                    if (generation != registerGeneration || !wantActive) {
                        adapter?.closeProfileProxy(BluetoothProfile.HID_DEVICE, connected)
                        return@runOnUiThread
                    }
                    hid = connected
                    submitRegistration(connected)
                }
            }

            override fun onServiceDisconnected(profile: Int) {
                activity.runOnUiThread {
                    registered = false
                    registering = false
                    hid = null
                    if (wantActive) emit("disconnected", "蓝牙 HID 服务已断开，回到本页后会重新登记")
                }
            }
        }, BluetoothProfile.HID_DEVICE)
        if (!opened) {
            registering = false
            wantActive = false
            replyError("hid", "系统没有蓝牙 HID Device 配置")
            emit("error", "系统没有蓝牙 HID Device 配置")
        }
    }

    private fun submitRegistration(device: BluetoothHidDevice) {
        val sdp = BluetoothHidDeviceAppSdpSettings(
            PAD_NAME,
            "Wireless Controller",
            "GameSir",
            BluetoothHidDevice.SUBCLASS2_GAMEPAD,
            DESCRIPTOR,
        )
        val ok = try {
            device.registerApp(sdp, null, null, executor, callback)
        } catch (_: SecurityException) {
            false
        }
        if (ok) return
        val retried = try {
            device.unregisterApp()
            device.registerApp(sdp, null, null, executor, callback)
        } catch (_: SecurityException) {
            false
        }
        if (retried) return
        registering = false
        wantActive = false
        val message = "蓝牙 HID 登记被系统拒绝。请保持本应用在前台后再试"
        replyError("hid", message)
        emit("error", message)
    }

    private fun inForeground(): Boolean = !activity.isFinishing && activity.hasWindowFocus()

    private fun replySuccess() {
        val waiting = pendingResult ?: return
        pendingResult = null
        waiting.success(null)
    }

    private fun replyError(code: String, message: String) {
        val waiting = pendingResult ?: return
        pendingResult = null
        waiting.error(code, message, null)
    }

    private val callback = object : BluetoothHidDevice.Callback() {
        override fun onAppStatusChanged(pluggedDevice: BluetoothDevice?, registeredNow: Boolean) {
            activity.runOnUiThread {
                registered = registeredNow
                registering = false
                if (registeredNow) {
                    replySuccess()
                    emit("discoverable", null)
                    return@runOnUiThread
                }
                // The system drops the registration whenever this activity leaves the
                // foreground, including while its own discoverable dialog is showing.
                // That is not a rejection; resume registers again.
                if (!wantActive || !inForeground()) return@runOnUiThread
                val generation = registerGeneration
                activity.window.decorView.postDelayed({
                    if (generation != registerGeneration || registered || !wantActive || !inForeground()) return@postDelayed
                    wantActive = false
                    val message = "蓝牙 HID 登记被系统拒绝。请保持本应用在前台后再试"
                    replyError("hid", message)
                    emit("error", message)
                }, 700)
            }
        }

        override fun onConnectionStateChanged(device: BluetoothDevice, state: Int) {
            when (state) {
                BluetoothProfile.STATE_CONNECTED -> {
                    host = device
                    send(report)
                    emit("connected", device.name)
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    if (host?.address == device.address) host = null
                    emit("disconnected", null)
                }
            }
        }

        override fun onGetReport(device: BluetoothDevice, type: Byte, id: Byte, bufferSize: Int) {
            try {
                hid?.replyReport(device, type, id, report)
            } catch (_: SecurityException) {
            }
        }

        override fun onVirtualCableUnplug(device: BluetoothDevice) {
            if (host?.address == device.address) host = null
            emit("disconnected", "鸭子拔出了这条 HID 连接")
        }
    }

    @SuppressLint("MissingPermission")
    private fun requestDiscoverable() {
        val intent = Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE)
            .putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, 300)
        activity.startActivityForResult(intent, REQUEST_DISCOVERABLE)
    }

    private fun emit(state: String, detail: String?) {
        val payload = mapOf("state" to state, "detail" to detail)
        activity.runOnUiThread { sink?.success(payload) }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
        sink = events
    }

    override fun onCancel(arguments: Any?) {
        sink = null
    }

    companion object {
        private const val TAG = "HidGamepad"
        const val REQUEST_PERMISSION = 4401
        const val REQUEST_DISCOVERABLE = 4402
        private const val PAD_NAME = "GameSir-Nova 2 Lite"
        private const val REPORT_ID = 1
        private const val REPORT_LENGTH = 9

        private val DESCRIPTOR = intArrayOf(
            0x05, 0x01, // Generic Desktop
            0x09, 0x05, // Game Pad
            0xA1, 0x01, // Application collection
            0x85, 0x01, // Report ID 1
            0x05, 0x09, // Button
            0x19, 0x01, // Usage min 1
            0x29, 0x0F, // Usage max 15
            0x15, 0x00,
            0x25, 0x01,
            0x75, 0x01, // 1 bit
            0x95, 0x0F, // 15 buttons
            0x81, 0x02,
            0x75, 0x01,
            0x95, 0x01, // pad to a byte
            0x81, 0x03,
            0x05, 0x01,
            0x09, 0x39, // Hat switch
            0x15, 0x00,
            0x25, 0x07,
            0x35, 0x00,
            0x46, 0x3B, 0x01,
            0x65, 0x14,
            0x75, 0x04,
            0x95, 0x01,
            0x81, 0x42, // data, variable, absolute, null state
            0x75, 0x04,
            0x95, 0x01,
            0x81, 0x03,
            0x09, 0x30, // X
            0x09, 0x31, // Y
            0x09, 0x32, // Z, RT
            0x09, 0x33, // Rx
            0x09, 0x34, // Ry
            0x09, 0x35, // Rz, LT
            0x15, 0x81, // -127
            0x25, 0x7F,
            0x75, 0x08,
            0x95, 0x06,
            0x81, 0x02,
            0xC0,
        ).map { it.toByte() }.toByteArray()
    }
}
