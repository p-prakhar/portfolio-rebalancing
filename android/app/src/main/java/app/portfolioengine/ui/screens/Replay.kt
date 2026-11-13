package app.portfolioengine.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.obj
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.components.ActionBar
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.AppTextButton
import app.portfolioengine.ui.components.Bullets
import app.portfolioengine.ui.components.BusyLine
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.EmptyState
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.Pill
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SideChip
import app.portfolioengine.ui.components.Stat
import app.portfolioengine.ui.components.SubScreen
import app.portfolioengine.ui.components.WindowChart
import app.portfolioengine.ui.components.prettyDate
import app.portfolioengine.ui.theme.LocalTokens
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The waiting window, replayed over days that have already happened. Instead of opening a window today and waiting
 * ten sessions, the engine works out where the window would stand had the check been run every day.
 */
@Composable
fun ReplayScreen(vm: MainViewModel, onBack: () -> Unit) {
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    var applying by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(attempt) {
        data = null
        error = null
        when (val r = vm.call("secretary_replay")) {
            is EngineResult.Ok -> data = r.obj
            is EngineResult.Err -> error = r.message
        }
    }

    fun useWindow(mode: String) {
        if (applying) return
        applying = true
        scope.launch {
            when (val r = vm.call("backdate_window", jsonOf("mode" to mode))) {
                is EngineResult.Err -> vm.say(r.message)
                is EngineResult.Ok -> {
                    vm.runCheck(refresh = false)
                    vm.say("Done. The Plan tab now reads the window from past prices.")
                    onBack()
                }
            }
            applying = false
        }
    }

    val d = data
    val legs = d.objects("legs")
    val waiting = legs.any { it.obj("now").str("decision") != "execute" }
    SubScreen(
        "Skip the wait", onBack,
        bottomBar = { if (d != null && legs.isNotEmpty()) ActionBar("Use this in my plan", enabled = !applying) { useWindow("now") } },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            BusyLine(d == null && error == null)
            error?.let { msg ->
                AppCard {
                    Text("Could not replay the window", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Muted(msg)
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(onClick = { attempt += 1 }) { Text("Try again") }
                }
            }
            if (d == null) {
                if (error == null) Muted("Replaying the last trading days")
                return@Column
            }
            if (legs.isEmpty()) {
                EmptyState(d.str("headline", "Nothing is waiting"), d.str("detail"))
                return@Column
            }
            val n = d.int("n", 10)
            val act = d.str("decision") == "execute"
            AppCard {
                if (act) Pill("ACT TODAY", MaterialTheme.colorScheme.onPrimary, MaterialTheme.colorScheme.primary)
                else Pill(if (d.str("decision") == "mixed") "PARTLY TODAY" else "KEEP WATCHING", MaterialTheme.colorScheme.onSecondaryContainer, MaterialTheme.colorScheme.secondaryContainer)
                Spacer(Modifier.height(10.dp))
                Text(d.str("headline"), style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(6.dp))
                Muted(d.str("detail"))
                Spacer(Modifier.height(10.dp))
                Muted("Prices to ${prettyDate(d.str("asof"))}. The window is $n trading days: watch the first ${d.int("cutoff")}, then act on the first price that beats everything seen, or on the last day.")
                if (d.str("execution") != "secretary") {
                    Spacer(Modifier.height(8.dp))
                    Muted("Waiting for a better price is switched off in settings, so the plan already says to place trades at the next session.")
                }
            }

            SectionTitle("Trade by trade")
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                for (leg in legs) LegCard(leg, n)
            }

            if (waiting) {
                Spacer(Modifier.height(12.dp))
                AppCard {
                    Text("Or count the full $n days from past prices", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Muted("This treats the window as opened $n trading days ago even though the plan was not asking for every trade then. It ends the wait today. Prices move close to a random walk, so on average this neither helps nor hurts the price you get.")
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = { useWindow("full") }, enabled = !applying) { Text("Count the full $n days") }
                }
            }

            SectionTitle("Is this fair?")
            AppCard {
                Bullets(
                    listOf(
                        "No peeking ahead. Each day's decision uses only prices up to that day, exactly as the daily check would have seen them.",
                        "A window starts on the first day the plan asked for the trade and kept asking every day since. Days before that are shown faint and do not count.",
                        "Waiting changes how spread out your results are, not the average. On prices that move like a random walk every fill rule gets the same average price, so skipping the wait costs nothing on average.",
                        "Trades that cut risk never wait.",
                    ),
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun LegCard(leg: JSONObject, n: Int) {
    val now = leg.obj("now")
    val prices = (0 until (leg.optJSONArray("prices")?.length() ?: 0)).map { leg.optJSONArray("prices")!!.optDouble(it) }
    val dates = leg.strings("dates")
    val opened = dates.indexOf(now.str("opened")).coerceAtLeast(0)
    val fired = if (now.isNullOrMissing("fired_i")) null else now.int("fired_i")
    val t = LocalTokens.current
    AppCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SideChip(leg.str("side"))
            Spacer(Modifier.width(10.dp))
            Text(leg.str("symbol"), style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            if (now.str("decision") == "execute") Pill("Today", MaterialTheme.colorScheme.onPrimaryContainer, MaterialTheme.colorScheme.primaryContainer)
            else Pill("${now.int("left")} day${if (now.int("left") == 1) "" else "s"} left", t.warn, t.warnContainer)
        }
        Spacer(Modifier.height(4.dp))
        Muted("${Fmt.inr(leg.num("value"))} to ${if (leg.str("side") == "sell") "sell" else "buy"}")
        Spacer(Modifier.height(12.dp))
        WindowChart(prices, opened, if (leg.bool("never_waits")) 0 else leg.int("cutoff"), fired)
        Spacer(Modifier.height(10.dp))
        Text(reasonText(leg, now, n), style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Stat("Window day", "${now.int("day")} of $n", Modifier.weight(1f))
            Stat("Today's price", "₹" + Fmt.price(prices.lastOrNull() ?: 0.0), Modifier.weight(1.2f))
            Stat(if (fired != null && fired < prices.lastIndex) "Rule's price" else "Window opened at", "₹" + Fmt.price(if (fired != null) now.num("fill") else prices.getOrElse(opened) { 0.0 }), Modifier.weight(1.2f))
        }
        Spacer(Modifier.height(6.dp))
        Disclosure("Day by day", subtitle = "On the plan for ${leg.int("run")} of the last ${prices.size} trading days in a row") {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (s in now.objects("steps")) {
                    val i = s.int("i")
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(prettyDate(dates.getOrElse(i) { "" }), style = MaterialTheme.typography.bodyMedium)
                            Muted(if (fired != null && i > fired) "After the rule traded" else if (s.str("decision") == "execute") "Act" else if (i - opened < leg.int("cutoff")) "Watching" else "Wait: no new best price")
                        }
                        Text("₹" + Fmt.price(prices.getOrElse(i) { 0.0 }), style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
        }
    }
}

private fun JSONObject?.isNullOrMissing(key: String): Boolean = this == null || !has(key) || isNull(key)

private fun reasonText(leg: JSONObject, now: JSONObject?, n: Int): String {
    val buy = leg.str("side") == "buy"
    return when (now.str("reason")) {
        "risk_exit" -> "This trade cuts risk, so it never waits for a better price. Place it today."
        "best_today" -> "Today is the ${if (buy) "lowest" else "highest"} price of the window so far, which is the rule's signal to act. Place it today."
        "last_day" -> "No day after the watching phase beat the prices seen before it, so the rule acts on the window's last day. That is today."
        "fired_earlier" -> {
            val edge = now.num("edge")
            "The rule would have traded on ${prettyDate(now.str("fired"))}. Today's price is ${Fmt.pct(kotlin.math.abs(edge))} ${if (edge >= 0) "better" else "worse"} for you than that day's. The wait is over either way: place it today."
        }
        "watching" -> "The plan started asking for this ${now.int("day")} trading day${if (now.int("day") == 1) "" else "s"} ago, so the window is still in its watching phase. ${now.int("left")} of $n days are left."
        else -> "Past the watching phase, and today's price has not beaten the best seen so far. The rule keeps waiting, for ${now.int("left")} more day${if (now.int("left") == 1) "" else "s"} at most."
    }
}
