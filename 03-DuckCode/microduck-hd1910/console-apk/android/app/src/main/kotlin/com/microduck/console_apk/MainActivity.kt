package com.microduck.console_apk

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var hid: HidGamepad? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        ConsoleRuntime.start(this)
        try {
            startForegroundService(Intent(this, ConsoleService::class.java))
        } catch (error: Exception) {
            Log.w("MicroDuck", "前台服务没有挂上，中控仍在本进程里运行", error)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val gamepad = HidGamepad(this)
        hid = gamepad
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.microduck.console_apk/hid")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "start" -> gamepad.start(result)
                    "stop" -> {
                        gamepad.stop()
                        result.success(null)
                    }
                    "send" -> {
                        val bytes = call.arguments as? ByteArray
                        if (bytes == null) result.error("report", "手柄报文无效", null)
                        else {
                            gamepad.send(bytes)
                            result.success(null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, "com.microduck.console_apk/hid_events")
            .setStreamHandler(gamepad)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == HidGamepad.REQUEST_PERMISSION) {
            hid?.onPermissions(grantResults.isNotEmpty() && grantResults.all { it == android.content.pm.PackageManager.PERMISSION_GRANTED })
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == HidGamepad.REQUEST_DISCOVERABLE) {
            hid?.onDiscoverableResult(resultCode)
        }
    }

    override fun onResume() {
        super.onResume()
        hid?.onHostResume()
    }

    override fun onDestroy() {
        if (!isChangingConfigurations) hid?.stop()
        super.onDestroy()
    }
}
