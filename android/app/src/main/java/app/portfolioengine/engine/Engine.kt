package app.portfolioengine.engine

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** What a bridge call returned: the `data` payload, or a message a person can read. */
sealed interface EngineResult {
    data class Ok(val data: Any?) : EngineResult {
        val obj: JSONObject get() = data as? JSONObject ?: JSONObject()
    }

    data class Err(val kind: String, val message: String) : EngineResult
}

/**
 * The Python engine (pe/mobile.py), embedded with Chaquopy.
 *
 * Every call goes through one background thread: Python runs one thing at a time anyway, and a single
 * thread keeps file writes (holdings, state) in order. Nothing here touches the main thread.
 */
class Engine(private val context: Context) {
    private val dispatcher = Executors.newSingleThreadExecutor { r -> Thread(r, "engine").apply { priority = Thread.NORM_PRIORITY - 1 } }
        .asCoroutineDispatcher()
    private var module: PyObject? = null

    val home: File get() = File(context.filesDir, "engine")

    private fun module(): PyObject {
        module?.let { return it }
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        val py = Python.getInstance()
        home.mkdirs()
        val env = py.getModule("os").get("environ")!!
        env.callAttr("__setitem__", "PE_HOME", home.absolutePath)
        env.callAttr("__setitem__", "PE_PRICE_SOURCE", "lite")
        // pandas and matplotlib-style libraries want a writable HOME and temp dir
        env.callAttr("__setitem__", "HOME", home.absolutePath)
        env.callAttr("__setitem__", "TMPDIR", context.cacheDir.absolutePath)
        py.getModule("os").callAttr("chdir", home.absolutePath)
        py.getModule("pe.yahoo_lite").callAttr("set_fetcher", HttpFetcher())
        val m = py.getModule("pe.mobile")
        m.callAttr("init")
        module = m
        return m
    }

    /** Call `pe.mobile.<fn>(*args)` and decode its JSON envelope. Never throws. */
    suspend fun call(fn: String, vararg args: Any?): EngineResult = withContext(dispatcher) {
        try {
            decode(module().callAttr(fn, *args).toString())
        } catch (t: Throwable) {
            EngineResult.Err("internal", t.message?.lineSequence()?.lastOrNull { it.isNotBlank() } ?: t.javaClass.simpleName)
        }
    }

    companion object {
        fun decode(json: String): EngineResult {
            val o = JSONObject(json)
            return if (o.optBoolean("ok")) {
                EngineResult.Ok(if (o.isNull("data")) null else o.get("data"))
            } else {
                EngineResult.Err(o.optString("kind", "internal"), o.optString("error", "Something went wrong."))
            }
        }
    }
}
