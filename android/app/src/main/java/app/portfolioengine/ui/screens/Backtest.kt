package app.portfolioengine.ui.screens

import androidx.compose.foundation.clickable
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.Bullets
import app.portfolioengine.ui.components.BusyLine
import app.portfolioengine.ui.components.ChartLayer
import app.portfolioengine.ui.components.ChartLine
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.FlowColumns
import app.portfolioengine.ui.components.HeroNumber
import app.portfolioengine.ui.components.LineChart
import app.portfolioengine.ui.components.MonthFlow
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.RankBar
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SideChip
import app.portfolioengine.ui.components.StackedAreaChart
import app.portfolioengine.ui.components.Stat
import app.portfolioengine.ui.components.SubScreen
import app.portfolioengine.ui.components.Tag
import app.portfolioengine.ui.components.prettyDate
import app.portfolioengine.ui.components.sleeveColor
import app.portfolioengine.ui.components.sleeveLabel
import app.portfolioengine.ui.components.sleeveSlot
import app.portfolioengine.ui.theme.LocalTokens
import org.json.JSONArray
import org.json.JSONObject

private const val MINE = "yours"

private fun JSONObject.doubles(key: String): List<Double> {
    val a: JSONArray = optJSONArray(key) ?: return emptyList()
    return (0 until a.length()).map { a.optDouble(it, 0.0) }
}

/**
 * How each strategy would have done with the money you actually put in, on the days you put it in.
 * Strategies report one by one, so the list fills while the rest are still being replayed.
 */
@Composable
fun BacktestScreen(vm: MainViewModel, onBack: () -> Unit) {
    var range by rememberSaveable { mutableStateOf("purchase") }
    var setup by remember { mutableStateOf<JSONObject?>(null) }
    val results = remember { mutableStateMapOf<String, JSONObject>() }
    var done by remember { mutableIntStateOf(0) }
    var total by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    var focus by rememberSaveable { mutableStateOf<String?>(null) }

    LaunchedEffect(range, attempt) {
        setup = null
        results.clear()
        done = 0
        total = 0
        error = null
        val payload = jsonOf("range" to range)
        when (val s = vm.call("backtest_setup", payload)) {
            is EngineResult.Err -> error = s.message
            is EngineResult.Ok -> {
                setup = s.obj
                val ids = s.obj.objects("strategies").map { it.str("id") }
                total = ids.size
                if (focus == null) focus = s.obj.str("current_policy").takeIf { it in ids && it != "buy_hold" }
                for (id in ids) {
                    (vm.call("backtest_run", id, payload) as? EngineResult.Ok)?.let { results[id] = it.obj }
                    done += 1
                }
            }
        }
    }

    SubScreen("Backtest on my holdings", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Muted("Your own purchases, replayed. Every strategy starts with the same holdings on the same days, so the only difference is what it did with the money.")
            Spacer(Modifier.height(12.dp))
            ChoiceRow(listOf("purchase" to "Since I bought", "1y" to "Last 12 months", "6m" to "Last 6 months"), range, { range = it })
            val busy = error == null && (setup == null || done < total)
            BusyLine(busy)
            if (busy) Muted(if (setup == null) "Loading prices" else "Replaying strategy ${minOf(done + 1, total)} of $total")

            error?.let { msg ->
                Spacer(Modifier.height(12.dp))
                AppCard {
                    Text("Could not run the backtest", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Muted(msg)
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(onClick = { attempt += 1 }) { Text("Try again") }
                }
            }

            val s = setup
            val mine = results[MINE]
            if (s != null && mine != null) {
                val dates = s.strings("dates")
                val invested = s.doubles("invested")
                val t = LocalTokens.current
                val picked = focus?.let { results[it] }?.takeIf { it.str("id") != MINE }

                Spacer(Modifier.height(12.dp))
                AppCard {
                    val gain = mine.num("gain_after_tax")
                    HeroNumber(
                        "What you did, after tax", Fmt.inrShort(mine.num("after_tax_value")),
                        note = "${Fmt.signedInrShort(gain)} on ${Fmt.inrShort(mine.num("invested"))} put in, ${prettyDate(s.str("start"))} to ${prettyDate(s.str("end"))}",
                        noteColor = if (gain >= 0) t.buy else t.sell,
                    )
                    if (picked != null) {
                        val diff = picked.num("after_tax_value") - mine.num("after_tax_value")
                        Spacer(Modifier.height(10.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "${picked.str("name")} would have ended ${Fmt.inrShort(kotlin.math.abs(diff))} ${if (diff >= 0) "ahead" else "behind"} after tax.",
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                }

                SectionTitle("Value over time")
                AppCard {
                    val lines = buildList {
                        add(ChartLine("What you did", t.series[0], mine.doubles("curve")))
                        if (picked != null) add(ChartLine(picked.str("name"), t.series[1], picked.doubles("curve")))
                        add(ChartLine("Money put in", MaterialTheme.colorScheme.outline, invested, dashed = true))
                    }
                    LineChart(dates, lines)
                    if (s.int("deposits") > 0) {
                        Spacer(Modifier.height(8.dp))
                        Muted("The steps in the dashed line are your later purchases. They are added for every strategy on the day you made them.")
                    }
                }

                SectionTitle("Every strategy, same money")
                AppCard {
                    val ranked = results.values.sortedByDescending { it.num("after_tax_value") }
                    val top = ranked.maxOf { maxOf(it.num("after_tax_value"), it.num("invested")) }
                    Muted("Value after tax if sold on the last day. The tick marks the money put in. Tap a row to compare it.")
                    Spacer(Modifier.height(4.dp))
                    ranked.forEachIndexed { i, r ->
                        if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        StrategyRow(
                            r, mine, top, selected = r.str("id") == focus,
                            current = policyOf(r.str("id")) == s.str("current_policy") && r.str("id") != MINE && r.str("id") != "hold_harvest",
                        ) { focus = if (focus == r.str("id") || r.str("id") == MINE) null else r.str("id") }
                    }
                    if (done < total) {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Muted("${total - done} more to come", Modifier.padding(vertical = 12.dp))
                    }
                }

                val inside = picked ?: mine
                SectionTitle("Inside: ${if (picked == null) "what you did" else inside.str("name")}")
                AppCard {
                    Text("Where the money sat", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(10.dp))
                    val layers = inside.objects("alloc").sortedBy { sleeveSlot(it.str("sleeve")).let { slot -> if (slot < 0) 99 else slot } }
                    StackedAreaChart(dates, layers.map { ChartLayer(sleeveLabel(it.str("sleeve")), sleeveColor(it.str("sleeve")), it.doubles("values")) })
                }
                Spacer(Modifier.height(12.dp))
                AppCard {
                    Text("Money moved each month", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(10.dp))
                    FlowColumns(inside.objects("flows").map { MonthFlow(it.str("month"), it.num("bought"), it.num("sold")) })
                    Spacer(Modifier.height(14.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Spacer(Modifier.height(12.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Stat("Fees paid", Fmt.inr(inside.num("costs")), Modifier.weight(1f))
                        Stat("Tax paid", Fmt.inr(inside.num("taxes_paid")), Modifier.weight(1f))
                        Stat("Tax if sold now", Fmt.inr(inside.num("tax_if_sold")), Modifier.weight(1.2f))
                    }
                    val moves = inside.objects("moves")
                    if (moves.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        Disclosure("Latest trades", subtitle = "${inside.int("trades")} trades on ${inside.int("trade_days")} days" + inside.int("harvests").let { if (it > 0) ", plus $it tax harvests" else "" }) {
                            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                for (m in moves.asReversed().take(12)) {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        SideChip(m.str("side"))
                                        Spacer(Modifier.width(10.dp))
                                        Column(Modifier.weight(1f)) {
                                            Text(m.str("symbol"), style = MaterialTheme.typography.bodyLarge)
                                            Muted(prettyDate(m.str("date")))
                                        }
                                        Text(Fmt.inrShort(m.num("value")), style = MaterialTheme.typography.titleMedium)
                                    }
                                }
                            }
                        }
                    }
                }

                SectionTitle("How to read this")
                AppCard {
                    Bullets(
                        buildList {
                            add("This is one path through one stretch of history. It shows what would have happened to your money. It does not prove one strategy is better: the 10-year test in the full report is the fair judge.")
                            add("Fees and Indian capital gains tax are included. Tax is paid each April, and the after-tax value also takes off the tax due if everything were sold on the last day.")
                            add("Only what you hold today is replayed. Holdings you sold earlier are not known to the app." + if (s.num("cash_left_out") > 0) " Your cash balance is left out." else "")
                            if (s.bool("clamped")) add("You bought before ${prettyDate(s.str("start"))}, but the strategies need about a year of prices before their first decision, so the replay starts there with what you held that day.")
                            addAll(s.strings("warnings"))
                        },
                    )
                    Spacer(Modifier.height(8.dp))
                    Muted(s.str("data_note"))
                }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

private fun policyOf(strategyId: String): String = if (strategyId == MINE || strategyId == "hold_harvest") "buy_hold" else strategyId

@Composable
private fun StrategyRow(r: JSONObject, mine: JSONObject, top: Double, selected: Boolean, current: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    val isMine = r.str("id") == MINE
    val color = when {
        isMine -> t.series[0]
        selected -> t.series[1]
        else -> MaterialTheme.colorScheme.outline
    }
    Column(Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = if (isMine) "Show only what you did" else "Compare with what you did", onClick = onClick).padding(vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                Text(r.str("name"), style = MaterialTheme.typography.bodyLarge, fontWeight = if (selected || isMine) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                if (current) {
                    Spacer(Modifier.width(8.dp))
                    Tag("Your setting")
                }
            }
            Spacer(Modifier.width(12.dp))
            Text(Fmt.inrShort(r.num("after_tax_value")), style = MaterialTheme.typography.titleMedium)
        }
        Spacer(Modifier.height(6.dp))
        RankBar(r.num("after_tax_value"), top, r.num("invested"), color)
        Spacer(Modifier.height(4.dp))
        val diff = r.num("after_tax_value") - mine.num("after_tax_value")
        val parts = buildList {
            if (!isMine) add(if (kotlin.math.abs(diff) < 1) "Same as you" else "${Fmt.inrShort(kotlin.math.abs(diff))} ${if (diff >= 0) "ahead" else "behind"}")
            add("worst fall ${Fmt.pct(-r.num("max_drawdown"), 0)}")
            add(r.int("trades").let { if (it == 0) "no trades" else "$it trade${if (it == 1) "" else "s"}" })
        }
        Muted(parts.joinToString(" · "))
    }
}
