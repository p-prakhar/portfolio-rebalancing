package app.portfolioengine

import android.app.Application
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.bool
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.obj
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.work.CheckWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.time.Duration
import java.time.LocalDateTime

data class UiState(
    val booting: Boolean = true,
    val bootError: String? = null,
    val hasHoldings: Boolean = false,
    val hasProfile: Boolean = false,
    val check: JSONObject? = null,
    val checking: Boolean = false,
    val checkError: String? = null,
    val holdings: JSONObject? = null,
    val settings: JSONObject? = null,
    val dailyCheck: Boolean = true,
)

/** Where an import is: nothing yet, working, waiting for one more answer, or showing what it would add. */
sealed interface ImportState {
    data object Idle : ImportState
    data class Working(val label: String) : ImportState
    data class Needs(val kind: String, val needs: List<String>, val message: String) : ImportState
    data class Preview(val data: JSONObject) : ImportState
    data class Failed(val message: String) : ImportState
    data class Done(val lots: Int) : ImportState
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val engine = (app as App).engine
    private val prefs = app.getSharedPreferences(App.PREFS, Context.MODE_PRIVATE)

    private val _state = MutableStateFlow(UiState(dailyCheck = prefs.getBoolean(App.PREF_DAILY_CHECK, true)))
    val state: StateFlow<UiState> = _state.asStateFlow()

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val messages = _messages.asSharedFlow()

    private val _import = MutableStateFlow<ImportState>(ImportState.Idle)
    val importState: StateFlow<ImportState> = _import.asStateFlow()
    private var importPaths: List<String> = emptyList()
    private var importText: String? = null
    private var importOptions: Map<String, Any?> = emptyMap()

    /** Files handed to the app by "Share" or "Open with", waiting for the import screen. */
    val incoming = MutableStateFlow<List<Uri>>(emptyList())

    init {
        boot()
    }

    fun boot() {
        _state.update { it.copy(booting = true, bootError = null) }
        viewModelScope.launch {
            when (val st = engine.call("status")) {
                is EngineResult.Err -> _state.update { it.copy(booting = false, bootError = st.message) }
                is EngineResult.Ok -> {
                    applyStatus(st.obj)
                    val last = (engine.call("last_check") as? EngineResult.Ok)?.data as? JSONObject
                    _state.update { it.copy(booting = false, check = last) }
                    CheckWorker.schedule(getApplication(), _state.value.dailyCheck && _state.value.hasHoldings)
                    if (_state.value.hasHoldings && isStale(last)) runCheck(refresh = false)
                    loadHoldings()
                }
            }
        }
    }

    private fun isStale(last: JSONObject?): Boolean {
        val at = last.str("checked_at")
        if (at.isEmpty()) return true
        return try {
            Duration.between(LocalDateTime.parse(at), LocalDateTime.now()).toHours() >= 6
        } catch (e: Exception) {
            true
        }
    }

    private fun applyStatus(o: JSONObject) {
        _state.update { it.copy(hasHoldings = o.bool("has_holdings"), hasProfile = o.bool("has_profile"), settings = o.obj("settings")) }
    }

    fun runCheck(refresh: Boolean) {
        if (_state.value.checking) return
        _state.update { it.copy(checking = true, checkError = null) }
        viewModelScope.launch {
            when (val r = engine.call("check", refresh, false)) {
                is EngineResult.Ok -> _state.update { it.copy(checking = false, check = r.obj, checkError = null) }
                is EngineResult.Err -> _state.update { it.copy(checking = false, checkError = r.message) }
            }
            loadHoldings()
        }
    }

    fun loadHoldings() {
        viewModelScope.launch {
            (engine.call("holdings") as? EngineResult.Ok)?.let { r -> _state.update { it.copy(holdings = r.obj) } }
        }
    }

    /** After anything that changes what is owned: reload, and re-run the check on cached prices. */
    fun holdingsChanged() {
        viewModelScope.launch {
            (engine.call("status") as? EngineResult.Ok)?.let { applyStatus(it.obj) }
            CheckWorker.schedule(getApplication(), _state.value.dailyCheck && _state.value.hasHoldings)
            if (_state.value.hasHoldings) {
                _state.update { it.copy(checking = false) }
                runCheck(refresh = false)
            } else {
                _state.update { it.copy(check = null, checkError = null) }
                loadHoldings()
            }
        }
    }

    /** A bridge call for a screen that keeps its own state. Errors come back as [EngineResult.Err]. */
    suspend fun call(fn: String, vararg args: Any?): EngineResult = engine.call(fn, *args)

    /** Fire a bridge call that changes holdings; shows the error as a message, otherwise refreshes. */
    fun mutate(fn: String, vararg args: Any?, done: (() -> Unit)? = null) {
        viewModelScope.launch {
            when (val r = engine.call(fn, *args)) {
                is EngineResult.Err -> _messages.tryEmit(r.message)
                is EngineResult.Ok -> {
                    done?.invoke()
                    holdingsChanged()
                }
            }
        }
    }

    fun say(message: String) {
        _messages.tryEmit(message)
    }

    fun profileSaved() {
        _state.update { it.copy(hasProfile = true) }
        holdingsChanged()
    }

    fun saveSettings(payload: String) {
        viewModelScope.launch {
            when (val r = engine.call("save_settings", payload)) {
                is EngineResult.Ok -> {
                    _state.update { it.copy(settings = r.obj) }
                    if (_state.value.hasHoldings) runCheck(refresh = false)
                }
                is EngineResult.Err -> _messages.tryEmit(r.message)
            }
        }
    }

    fun setDailyCheck(enabled: Boolean) {
        prefs.edit().putBoolean(App.PREF_DAILY_CHECK, enabled).apply()
        _state.update { it.copy(dailyCheck = enabled) }
        CheckWorker.schedule(getApplication(), enabled && _state.value.hasHoldings)
    }

    fun closeWindow() {
        viewModelScope.launch {
            engine.call("reset_window")
            runCheck(refresh = false)
        }
    }

    // ------------------------------------------------------------------ imports
    fun importFiles(uris: List<Uri>) {
        if (uris.isEmpty()) return
        _import.value = ImportState.Working("Reading ${if (uris.size == 1) "the file" else "${uris.size} files"}")
        viewModelScope.launch {
            val paths = try {
                withContext(Dispatchers.IO) { uris.map { copyToCache(it) } }
            } catch (e: Exception) {
                _import.value = ImportState.Failed("Could not read that file (${e.javaClass.simpleName}). Try picking it again.")
                return@launch
            }
            importPaths = paths
            importText = null
            importOptions = emptyMap()
            preview()
        }
    }

    fun importTyped(text: String) {
        importPaths = emptyList()
        importText = text
        importOptions = emptyMap()
        _import.value = ImportState.Working("Reading your lines")
        viewModelScope.launch { preview() }
    }

    /** The answers to what the engine asked for (password, ticker, rate, date). */
    fun importAnswer(options: Map<String, Any?>) {
        importOptions = importOptions + options
        _import.value = ImportState.Working("Reading")
        viewModelScope.launch { preview() }
    }

    private suspend fun preview() {
        val payload = JSONObject()
        if (importText != null) payload.put("text", importText) else payload.put("paths", org.json.JSONArray(importPaths))
        for ((k, v) in importOptions) if (v != null && v.toString().isNotBlank()) payload.put(k, v)
        when (val r = engine.call("import_preview", payload.toString())) {
            is EngineResult.Err -> _import.value = ImportState.Failed(r.message)
            is EngineResult.Ok -> {
                val d = r.obj
                val needs = d.strings("needs")
                _import.value = if (needs.isNotEmpty()) ImportState.Needs(d.str("kind"), needs, d.str("message")) else ImportState.Preview(d)
            }
        }
    }

    fun importCommit(mode: String) {
        val lots = (_import.value as? ImportState.Preview)?.data?.optInt("lots") ?: 0
        _import.value = ImportState.Working("Saving")
        viewModelScope.launch {
            when (val r = engine.call("import_commit", mode)) {
                is EngineResult.Err -> _import.value = ImportState.Failed(r.message)
                is EngineResult.Ok -> {
                    clearImportCache()
                    _import.value = ImportState.Done(lots)
                    holdingsChanged()
                }
            }
        }
    }

    fun importReset() {
        _import.value = ImportState.Idle
        importPaths = emptyList()
        importText = null
        importOptions = emptyMap()
        viewModelScope.launch(Dispatchers.IO) { clearImportCache() }
    }

    private fun importDir(): File = File(getApplication<App>().cacheDir, "imports").apply { mkdirs() }

    private fun clearImportCache() {
        importDir().listFiles()?.forEach { it.delete() }
    }

    /** Statements are copied into the app's private cache for parsing and deleted right after the import. */
    private fun copyToCache(uri: Uri): String {
        val ctx = getApplication<App>()
        var name = "import"
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) name = c.getString(0)
        }
        name = name.replace(Regex("""[^\w.\- ()]"""), "_")
        if (!name.contains('.')) {
            val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(ctx.contentResolver.getType(uri) ?: "") ?: "csv"
            name = "$name.$ext"
        }
        var out = File(importDir(), name)
        var i = 1
        while (out.exists()) out = File(importDir(), "${i++}_$name")
        ctx.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "no stream" }
            out.outputStream().use { input.copyTo(it) }
        }
        return out.absolutePath
    }

    // ------------------------------------------------------------------ backup
    suspend fun exportBackup(): File? {
        val dir = File(getApplication<App>().cacheDir, "exports").apply { mkdirs() }
        val out = File(dir, "portfolio-engine-backup.zip")
        return when (val r = engine.call("export_backup", out.absolutePath)) {
            is EngineResult.Ok -> out
            is EngineResult.Err -> {
                _messages.tryEmit(r.message)
                null
            }
        }
    }
}

fun payloadOf(vararg pairs: Pair<String, Any?>): String = jsonOf(*pairs)
