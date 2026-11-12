package app.portfolioengine.ui.screens

import android.annotation.SuppressLint
import android.content.Intent
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.portfolioengine.MainViewModel
import app.portfolioengine.UiState
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.bool
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SubScreen
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

@Composable
private fun LinkRow(title: String, body: String, busy: Boolean = false, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = !busy, onClick = onClick).padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Muted(body)
        }
        if (busy) CircularProgressIndicator(Modifier.height(20.dp).padding(end = 2.dp), strokeWidth = 2.dp)
        else Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Rule() = HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

/** Tab 4: everything that is not the daily question. */
@Composable
fun MoreTab(vm: MainViewModel, state: UiState, go: (String) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var confirmReset by remember { mutableStateOf(false) }
    val restore = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            vm.importFiles(listOf(uri))
            go(Routes.IMPORT)
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        Text("More", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 12.dp, bottom = 8.dp))
        AppCard {
            LinkRow("Profile and income", if (state.hasProfile) "Age, risk appetite, tax slab, safety net" else "Not set yet. Makes the tax numbers exact.") { go(Routes.PROFILE) }
            Rule()
            LinkRow("Fixed deposits", "After-tax yield and the cost of breaking early") { go(Routes.DEPOSITS) }
            Rule()
            LinkRow("Other assets", "EPF, PPF, NPS, gold, property, savings") { go(Routes.OTHERS) }
        }
        SectionTitle("Understand")
        AppCard {
            LinkRow("Reports", "Track record, every asset class compared, crash guard, gold prices") { go(Routes.REPORTS) }
            Rule()
            LinkRow("Strategy and settings", "How the engine decides, and the daily check") { go(Routes.SETTINGS) }
        }
        SectionTitle("Your data")
        AppCard {
            LinkRow("Save a backup", "A zip of your holdings, profile and deposits to keep or move to another phone") {
                scope.launch {
                    val f = vm.exportBackup() ?: return@launch
                    val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
                    val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    ctx.startActivity(Intent.createChooser(send, "Save backup"))
                }
            }
            Rule()
            LinkRow("Restore a backup", "Pick a backup zip, or a holdings.yaml from the engine on your computer") { restore.launch(arrayOf("application/zip", "application/x-yaml", "application/yaml", "application/octet-stream", "text/*")) }
            Rule()
            LinkRow("Start over", "Remove all holdings and begin again. Your profile stays.") { confirmReset = true }
        }
        Spacer(Modifier.height(16.dp))
        Muted("Everything stays on this phone. The app only goes online for market prices and fund NAVs. It gives decision support and never places orders. Tax rules change with each Budget: check with a CA before acting.")
        Spacer(Modifier.height(24.dp))
    }
    if (confirmReset) {
        AlertDialog(
            onDismissRequest = { confirmReset = false },
            title = { Text("Start over?") },
            text = { Text("This removes every holding from the app. Save a backup first if you may want them back.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmReset = false
                    vm.mutate("clear_holdings")
                }) { Text("Remove holdings") }
            },
            dismissButton = { TextButton(onClick = { confirmReset = false }) { Text("Cancel") } },
        )
    }
}

@Composable
fun ReportsScreen(vm: MainViewModel, onBack: () -> Unit, open: (String, String, Boolean) -> Unit) {
    var kinds by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var busy by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        ((vm.call("report_kinds") as? EngineResult.Ok)?.data as? JSONArray)?.let { a -> kinds = (0 until a.length()).map { a.getJSONObject(it) } }
    }
    fun run(id: String, fn: String, scripts: Boolean, vararg args: Any?) {
        if (busy != null) return
        busy = id
        scope.launch {
            when (val r = vm.call(fn, *args)) {
                is EngineResult.Err -> vm.say(r.message)
                is EngineResult.Ok -> open(r.obj.str("path"), r.obj.str("title", "Full report"), scripts)
            }
            busy = null
        }
    }
    SubScreen("Reports", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            AppCard {
                LinkRow("Full interactive report", "Track record over the last 12 months, the drift slider, markets and how it decides. Takes a minute to build.", busy == "full") {
                    run("full", "full_report", true, false, false)
                }
                for (k in kinds) {
                    Rule()
                    LinkRow(k.str("title"), k.str("detail") + if (k.bool("online")) " Needs the internet." else "", busy == k.str("id")) { run(k.str("id"), "report", false, k.str("id")) }
                }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

/** Shows a page the engine wrote into the app's private storage. Scripts only for the engine's own interactive report. */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebScreen(path: String, title: String, scripts: Boolean, onBack: () -> Unit) {
    // paint the theme background first so a dark page never flashes white while it loads
    val bg = MaterialTheme.colorScheme.background.toArgb()
    SubScreen(title, onBack) { pad ->
        AndroidView(
            modifier = Modifier.fillMaxSize().padding(pad),
            factory = { c ->
                WebView(c).apply {
                    setBackgroundColor(bg)
                    webViewClient = WebViewClient()
                    settings.javaScriptEnabled = scripts
                    settings.allowFileAccess = true
                    settings.allowContentAccess = false
                    settings.domStorageEnabled = scripts
                    settings.builtInZoomControls = true
                    settings.displayZoomControls = false
                    loadUrl("file://" + File(path).absolutePath)
                }
            },
        )
    }
}

@Composable
fun SettingsScreen(vm: MainViewModel, onBack: () -> Unit) {
    val state by vm.state.collectAsStateWithLifecycle()
    val s = state.settings
    val notify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    SubScreen("Strategy and settings", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            SectionTitle("Daily check")
            AppCard {
                ToggleRow("Check once a day", "Runs in the background and notifies you only when a rebalance looks worth it or a waiting trade should be placed", state.dailyCheck) {
                    vm.setDailyCheck(it)
                    if (it && android.os.Build.VERSION.SDK_INT >= 33) notify.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            SectionTitle("How trades are timed")
            AppCard {
                ToggleRow("Wait for a better price", "Watches prices for a few days before saying act (the secretary rule). Off means act at the next session. Risk-cutting exits never wait.", s.str("execution", "secretary") == "secretary") {
                    vm.saveSettings(jsonOf("execution" to if (it) "secretary" else "immediate"))
                }
                Rule()
                ToggleRow("Let the crash guard cut risk", "Off by default: in 10 years of data it lowered returns. Its warnings show either way.", s.bool("crash_enabled")) {
                    vm.saveSettings(jsonOf("crash_enabled" to it))
                }
            }
            SectionTitle("Strategy")
            AppCard {
                val all = s.objects("policies")
                val current = s.str("policy")
                // the three most people want, plus whichever is selected; the rest stay one tap away
                val front = all.filterIndexed { i, p -> i < 3 || p.str("id") == current }
                front.forEachIndexed { i, p ->
                    if (i > 0) Rule()
                    PolicyRow(p, current) { vm.saveSettings(jsonOf("policy" to it)) }
                }
                val rest = all - front.toSet()
                if (rest.isNotEmpty()) {
                    Rule()
                    Disclosure("More strategies", subtitle = "${rest.size} others the engine can run") {
                        rest.forEach { p -> PolicyRow(p, current) { vm.saveSettings(jsonOf("policy" to it)) } }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Muted("Changing the strategy changes the plan, not your holdings. Each one is judged over 10 years in the full report.")
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun PolicyRow(p: JSONObject, current: String, pick: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { pick(p.str("id")) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected = current == p.str("id"), onClick = { pick(p.str("id")) })
        Column(Modifier.weight(1f).padding(start = 4.dp)) {
            Text(p.str("name"), style = MaterialTheme.typography.bodyLarge)
            Muted(p.str("detail"))
        }
    }
}
