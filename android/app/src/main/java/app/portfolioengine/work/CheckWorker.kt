package app.portfolioengine.work

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.portfolioengine.App
import app.portfolioengine.MainActivity
import app.portfolioengine.R
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.obj
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import java.util.concurrent.TimeUnit

/**
 * The periodic check: once a day, when there is a network, run the engine and speak up only when there is
 * something to do (the call turned to REBALANCE, or a waiting trade should be placed today).
 */
class CheckWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as App
        val res = app.engine.call("check", true, false)
        if (res !is EngineResult.Ok) {
            return if (res is EngineResult.Err && res.kind == "no_prices" && runAttemptCount < 2) Result.retry() else Result.success()
        }
        val d = res.obj
        val call = d.obj("verdict").str("call")
        val execute = d.strings("timing").filter { it.contains("EXECUTE TODAY") || it.contains("execute now") }
        val key = d.str("asof") + "|" + call + "|" + execute.size
        val prefs = app.getSharedPreferences(App.PREFS, Context.MODE_PRIVATE)
        if ((call == "REBALANCE" || execute.isNotEmpty()) && prefs.getString(App.PREF_LAST_NOTIFIED, "") != key) {
            val title = if (execute.isNotEmpty()) "Place ${execute.size} waiting trade${if (execute.size == 1) "" else "s"} today" else "A rebalance looks worth it"
            val text = if (execute.isNotEmpty()) execute.first().replace("**", "") else d.obj("verdict").str("headline")
            notify(app, title, text)
            prefs.edit().putString(App.PREF_LAST_NOTIFIED, key).apply()
        }
        return Result.success()
    }

    private fun notify(ctx: Context, title: String, text: String) {
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            android.os.Build.VERSION.SDK_INT >= 33
        ) return
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val n = NotificationCompat.Builder(ctx, App.CHANNEL_CHECKS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(ctx).notify(1, n)
    }

    companion object {
        private const val NAME = "daily-check"

        fun schedule(ctx: Context, enabled: Boolean) {
            val wm = WorkManager.getInstance(ctx)
            if (!enabled) {
                wm.cancelUniqueWork(NAME)
                return
            }
            val req = PeriodicWorkRequestBuilder<CheckWorker>(24, TimeUnit.HOURS, 4, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).setRequiresBatteryNotLow(true).build())
                .build()
            wm.enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}
