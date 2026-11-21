package com.microduck.console_apk

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread

object ConsoleRuntime {
    private const val TAG = "MicroDuck"
    private val started = AtomicBoolean(false)

    fun start(context: Context) {
        if (!started.compareAndSet(false, true)) return
        val app = context.applicationContext
        thread(name = "microduck-console", isDaemon = true) {
            try {
                val root = File(app.filesDir, "console")
                unpack(app, root)
                if (!Python.isStarted()) Python.start(AndroidPlatform(app))
                Python.getInstance().getModule("phone_console").callAttr("main", root.absolutePath)
            } catch (error: Exception) {
                Log.e(TAG, "本机中控没有跑起来", error)
                started.set(false)
            }
        }
    }

    private fun unpack(context: Context, root: File) {
        val zip = File(context.filesDir, "console-runtime.zip")
        context.assets.open("console-runtime.zip").use { input ->
            FileOutputStream(zip).use { output -> input.copyTo(output) }
        }
        val stamp = File(context.filesDir, "console.stamp")
        val digest = sha256(zip)
        if (stamp.exists() && stamp.readText() == digest && File(root, "console.py").exists()) return
        val keptLogs = File(context.cacheDir, "console-logs")
        val logs = File(root, "logs")
        if (keptLogs.exists()) keptLogs.deleteRecursively()
        if (logs.exists()) logs.copyRecursively(keptLogs, overwrite = true)
        root.deleteRecursively()
        root.mkdirs()
        ZipInputStream(zip.inputStream()).use { archive ->
            while (true) {
                val entry = archive.nextEntry ?: break
                val name = entry.name.replace('\\', '/')
                if (name.isEmpty() || name.endsWith("/")) continue
                val out = File(root, name)
                val canonical = out.canonicalPath
                if (!canonical.startsWith(root.canonicalPath + File.separator)) continue
                out.parentFile?.mkdirs()
                FileOutputStream(out).use { archive.copyTo(it) }
            }
        }
        if (keptLogs.exists()) keptLogs.copyRecursively(File(root, "logs"), overwrite = true)
        stamp.writeText(digest)
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1024 * 64)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

class ConsoleService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "MicroDuck 中控", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setContentTitle("MicroDuck")
            .setContentText("中控在本机运行，可连接局域网里的鸭子")
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, notification)
        }
        ConsoleRuntime.start(this)
        return START_STICKY
    }

    companion object {
        private const val CHANNEL = "microduck-console"
    }
}
