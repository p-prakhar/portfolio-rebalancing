package app.portfolioengine.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.ActionBar
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SubScreen

/** What the main button on a guide does once the steps are done. */
enum class SourceAction { FILE, FUND, TYPED }

/**
 * One place people keep investments, and the shortest way to get it into the app from a phone.
 * Steps are written for a phone browser. Broker menus move, so each step names the words to look for.
 */
data class Source(
    val id: String,
    val name: String,
    val sub: String,
    val steps: List<String>,
    val url: String? = null,
    val urlLabel: String? = null,
    val note: String? = null,
    val action: SourceAction = SourceAction.FILE,
    val actionLabel: String = "I have the file, choose it",
)

val SOURCES = listOf(
    Source(
        "zerodha", "Zerodha", "Kite and Console",
        listOf(
            "Open Console in your browser and sign in with your Kite login. The Kite app itself has no download.",
            "Go to Reports, then Tradebook. Pick Equity and a date range, then download the CSV.",
            "Console gives about one financial year at a time. Repeat for each year you bought in.",
            "Come back here and choose all the files together.",
        ),
        url = "https://console.zerodha.com/reports/tradebook", urlLabel = "Open Zerodha Console",
        note = "In a hurry? Portfolio, then Holdings, then Download gives one file. It has no purchase dates, so you will be asked roughly when you bought.",
    ),
    Source(
        "groww", "Groww", "Stocks and ETFs",
        listOf(
            "Open groww.in in your browser and sign in.",
            "Tap your profile picture, then Reports.",
            "Under Stocks, download the order history for the full period. The holdings statement also works.",
            "Come back here and choose the downloaded file.",
        ),
        url = "https://groww.in", urlLabel = "Open Groww",
        note = "Mutual funds held on Groww are quicker to add by name. Go back and pick Mutual funds.",
    ),
    Source(
        "upstox", "Upstox", "Stocks and ETFs",
        listOf(
            "Open the Upstox account page in your browser and sign in.",
            "Go to Reports and open the trade history. Pick the full period you traded in.",
            "Download it as CSV or Excel. A holdings download also works.",
            "Come back here and choose the downloaded file.",
        ),
        url = "https://account.upstox.com", urlLabel = "Open Upstox",
    ),
    Source(
        "broker", "Another Indian broker", "Angel One, ICICI Direct, HDFC Securities, Dhan and others",
        listOf(
            "Sign in on the broker's website. Most keep downloads there, not in the app.",
            "Look for Reports or Statements, then trade history, tradebook or transaction statement.",
            "Pick the full period and download as CSV or Excel. A holdings download also works.",
            "Come back here and choose the downloaded file.",
        ),
        note = "Any table with symbol, date, buy or sell, quantity and price is understood. If the app cannot read yours, type the holdings instead: it takes a line each.",
    ),
    Source(
        "funds", "Mutual funds", "Any fund house, Coin, Kuvera, Groww, a distributor",
        listOf(
            "Open your fund app or latest statement and note each fund's name, what you put in, and roughly when.",
            "Tap the button below and search the fund by name.",
            "Enter the amount and date. Units are worked out from that day's NAV.",
            "Repeat for each fund. A SIP can go in as one line with its middle date to begin with.",
        ),
        note = "The CAS statement PDF cannot be read on the phone yet. It can be read by the engine on a computer, and the result moved here as a backup file.",
        action = SourceAction.FUND, actionLabel = "Add a fund",
    ),
    Source(
        "etrade", "E*TRADE stock plan", "RSUs and ESPP from an employer",
        listOf(
            "Open etrade.com in your browser and sign in. The download is on the website, not in the app.",
            "Go to At Work, then My Account, then Benefit History.",
            "Tap Download, then Download Expanded. You get one Excel file with both RSUs and ESPP.",
            "Come back here and choose it. Shares already sold are worked out from the file.",
        ),
        url = "https://us.etrade.com", urlLabel = "Open E*TRADE",
    ),
    Source(
        "us", "A US broker", "Interactive Brokers, Vested, INDmoney and others",
        listOf(
            "Sign in on the broker's website or app and find Reports, Statements or Activity.",
            "Export your trades as CSV for the full period, with symbol, date, buy or sell, quantity and price.",
            "Come back here and choose the file. Dollar prices are converted to rupees at each day's rate.",
        ),
    ),
    Source(
        "computer", "The engine on my computer", "Move what is already set up",
        listOf(
            "On the computer, find config/holdings.yaml in the engine folder.",
            "Send it to this phone any way you like: mail, a cloud drive or a cable.",
            "Choose it here. It replaces what is in the app.",
        ),
    ),
    Source(
        "none", "No statement, I know what I hold", "Type it in a minute",
        listOf(
            "Write one holding per line: the symbol, then either quantity and price or just the amount.",
            "Add the date if you know it. For example: NIFTYBEES 5 lakh 14/08/2024",
            "You see exactly what will be added before anything is saved.",
        ),
        action = SourceAction.TYPED, actionLabel = "Type my holdings",
    ),
)

/** The app list people pick from. Recognising your own broker is quicker than reading about file types. */
@Composable
fun SourceList(open: (Source) -> Unit) {
    AppCard {
        SOURCES.forEachIndexed { i, s ->
            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable { open(s) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(s.name, style = MaterialTheme.typography.bodyLarge)
                    Muted(s.sub)
                }
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** The same list after first run, from the add sheet. */
@Composable
fun SourcesScreen(go: (String) -> Unit, onBack: () -> Unit) {
    SubScreen("Import from an app", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Spacer(Modifier.height(8.dp))
            Muted("Pick where the investments are to see the steps.")
            Spacer(Modifier.height(12.dp))
            SourceList { go(Routes.guide(it.id)) }
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
fun NumberedSteps(steps: List<String>) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        steps.forEachIndexed { i, step ->
            Row {
                Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer, contentColor = MaterialTheme.colorScheme.onPrimaryContainer, modifier = Modifier.size(28.dp)) {
                    Box(contentAlignment = Alignment.Center) { Text("${i + 1}", style = MaterialTheme.typography.labelLarge) }
                }
                Spacer(Modifier.width(12.dp))
                Text(step, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f).padding(top = 2.dp))
            }
        }
    }
}

/** Steps for one app, a link straight to the right page, and the one button that finishes the job. */
@Composable
fun SourceGuideScreen(vm: MainViewModel, id: String, go: (String) -> Unit, onBack: () -> Unit) {
    val s = SOURCES.firstOrNull { it.id == id } ?: SOURCES.first()
    val links = LocalUriHandler.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            vm.importFiles(uris)
            go(Routes.IMPORT)
        }
    }
    val act: () -> Unit = {
        when (s.action) {
            SourceAction.FILE -> picker.launch(IMPORT_MIME)
            SourceAction.FUND -> go(Routes.ADD_FUND)
            SourceAction.TYPED -> go(Routes.IMPORT_TYPED)
        }
    }
    SubScreen(s.name, onBack, bottomBar = { ActionBar(s.actionLabel, onClick = act) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Spacer(Modifier.height(8.dp))
            AppCard { NumberedSteps(s.steps) }
            if (s.url != null) {
                Spacer(Modifier.height(12.dp))
                OutlinedButton(onClick = { runCatching { links.openUri(s.url) } }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                    Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(s.urlLabel ?: "Open the website")
                }
            }
            if (s.note != null) {
                Spacer(Modifier.height(12.dp))
                Muted(s.note)
            }
            if (s.action == SourceAction.FILE) {
                SectionTitle("Even quicker")
                AppCard {
                    Muted("When the download finishes, tap its notification or find it in your file manager, choose Share or Open with, and pick Portfolio Engine. The app opens straight on the review screen.")
                }
                Spacer(Modifier.height(12.dp))
                Muted("Files are read on this phone and turned into tax lots. Nothing is uploaded, and nothing is saved until you confirm.")
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

/** The same guides, folded, for screens that cannot navigate away (the import screen mid-flow). */
@Composable
fun FileGuides() {
    SOURCES.filter { it.action == SourceAction.FILE }.forEach { s ->
        Disclosure(s.name, subtitle = s.sub) {
            NumberedSteps(s.steps)
            if (s.note != null) {
                Spacer(Modifier.height(10.dp))
                Muted(s.note)
            }
        }
    }
}
