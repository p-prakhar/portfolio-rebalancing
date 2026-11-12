package app.portfolioengine.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.ActionBar
import app.portfolioengine.ui.components.AmountField
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SubScreen
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate

/** Every type the importer understands; the picker shows them all so nothing has to be renamed first. */
val IMPORT_MIME = arrayOf(
    "text/*", "application/pdf", "application/zip", "application/vnd.ms-excel", "application/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/x-yaml", "application/yaml", "application/octet-stream",
)

/** First run: four ways in, the easiest first. */
@Composable
fun OnboardingScreen(vm: MainViewModel, go: (String) -> Unit) {
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            vm.importFiles(uris)
            go(Routes.IMPORT)
        }
    }
    Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
        Spacer(Modifier.height(32.dp))
        Text("What do you own?", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(8.dp))
        Muted("Tell the engine once. It then checks every day whether a rebalance is worth its tax and fees, and says why. Everything stays on this phone.")
        Spacer(Modifier.height(24.dp))
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            WayIn(Icons.Filled.UploadFile, "Import a file", "Broker tradebook or holdings export, E*TRADE Benefit History, mutual fund CAS, or a backup. The app works out which it is.") { picker.launch(IMPORT_MIME) }
            WayIn(Icons.Filled.Dashboard, "Start from a typical portfolio", "Pick something close to yours and a rough amount. Fix the details later.") { go(Routes.STARTER) }
            WayIn(Icons.Filled.EditNote, "Type or paste a list", "One holding per line, for example: TCS 12 3900 2024-09-16") { go(Routes.IMPORT_TYPED) }
            WayIn(Icons.Filled.Edit, "Add one holding", "Search a stock, ETF or mutual fund and enter what you paid.") { go(Routes.ADD) }
        }
        SectionTitle("Where do I find my files?")
        AppCard { FileGuides() }
        Spacer(Modifier.height(16.dp))
        Muted("You can also share a file to this app from your mail or file manager.")
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun WayIn(icon: ImageVector, title: String, body: String, onClick: () -> Unit) {
    AppCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Muted(body)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
fun FileGuides() {
    Disclosure("Zerodha") {
        Muted("console.zerodha.com > Reports > Tradebook > Equity > pick the dates > download CSV. Console gives about one financial year at a time, so download each year you traded and pick all the files together. The tradebook is better than the holdings export because it has purchase dates.")
    }
    Disclosure("Groww, Upstox and other Indian brokers") {
        Muted("Download the order or trade history as CSV or Excel from the reports section. A holdings export also works: you will be asked roughly when you bought, because it has no dates.")
    }
    Disclosure("Mutual funds (any fund house)") {
        Muted("Request a detailed Consolidated Account Statement from camsonline.com or mfcentral.com for the period from your first investment to today. It arrives by email as a PDF with the password you chose.")
    }
    Disclosure("E*TRADE stock plan (RSU, ESPP)") {
        Muted("etrade.com > At Work > My Account > Benefit History > Download > Download Expanded. The Excel file holds both RSUs and ESPP. Shares already sold are worked out from it.")
    }
    Disclosure("Interactive Brokers and other US brokers") {
        Muted("Export trades as CSV with symbol, date, buy or sell, quantity, price and currency. Dollar prices are converted to rupees.")
    }
    Disclosure("The engine on your computer") {
        Muted("Share config/holdings.yaml from the computer to this phone and open it here. It replaces what is in the app.")
    }
}

/** A typical portfolio, an amount and a rough date: enough for a first check. */
@Composable
fun StarterScreen(vm: MainViewModel, onBack: () -> Unit) {
    var starters by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var picked by rememberSaveable { mutableStateOf("") }
    var amount by rememberSaveable { mutableStateOf("") }
    var age by rememberSaveable { mutableStateOf("old") }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().minusMonths(18).toString()) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        ((vm.call("starters") as? EngineResult.Ok)?.data as? JSONArray)?.let { a -> starters = (0 until a.length()).map { a.getJSONObject(it) } }
    }
    val amt = Fmt.parseAmount(amount)
    val apply: () -> Unit = {
                    busy = true
                    scope.launch {
                        when (val r = vm.call("apply_starter", jsonOf("id" to picked, "amount_inr" to amt, "buy_date" to date))) {
                            is EngineResult.Err -> {
                                error = r.message
                                busy = false
                            }
                            is EngineResult.Ok -> {
                                vm.holdingsChanged()
                                onBack()
                            }
                        }
                    }
                }
    SubScreen("Start from a typical portfolio", onBack, bottomBar = {
        ActionBar(if (busy) "Setting up" else "Use this portfolio", enabled = !busy && picked.isNotEmpty() && amt != null && amt > 0, error = error, onClick = apply)
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Muted("Pick the closest one. You can add, remove and correct holdings afterwards.")
            Spacer(Modifier.height(12.dp))
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                for (s in starters) {
                    val on = picked == s.str("id")
                    AppCard(onClick = { picked = s.str("id") }) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(s.str("title"), style = MaterialTheme.typography.titleMedium, color = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                                Muted(s.str("detail"))
                            }
                            androidx.compose.material3.RadioButton(selected = on, onClick = { picked = s.str("id") })
                        }
                    }
                }
            }
            Spacer(Modifier.height(20.dp))
            AmountField(amount, { amount = it }, "Roughly how much is it worth?", help = "For example 16 lakh")
            Spacer(Modifier.height(4.dp))
            Text("When did you buy most of it?", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            ChoiceRow(listOf("old" to "Over a year ago", "new" to "Within the last year", "date" to "Pick a date"), age, {
                age = it
                if (it == "old") date = LocalDate.now().minusMonths(18).toString()
                if (it == "new") date = LocalDate.now().minusMonths(4).toString()
            })
            if (age == "date") {
                Spacer(Modifier.height(8.dp))
                DateField("Purchase date", date, { date = it })
            }
            Spacer(Modifier.height(6.dp))
            Muted("The date only decides long-term versus short-term tax. Units are worked out from that day's closing price.")
            Spacer(Modifier.height(32.dp))
        }
    }
}
