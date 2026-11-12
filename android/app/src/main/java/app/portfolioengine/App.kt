package app.portfolioengine

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import app.portfolioengine.engine.Engine

class App : Application() {
    /** One engine for the whole process; it starts Python lazily on its own thread. */
    val engine: Engine by lazy { Engine(this) }

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(CHANNEL_CHECKS, getString(R.string.channel_checks), NotificationManager.IMPORTANCE_DEFAULT)
        channel.description = getString(R.string.channel_checks_desc)
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_CHECKS = "checks"
        const val PREFS = "app"
        const val PREF_DAILY_CHECK = "daily_check"
        const val PREF_LAST_NOTIFIED = "last_notified"
    }
}
