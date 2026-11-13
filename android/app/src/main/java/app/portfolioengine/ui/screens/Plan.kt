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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.UiState
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.obj
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.AppTextButton
import app.portfolioengine.ui.components.Bullets
import app.portfolioengine.ui.components.BusyLine
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.EmptyState
import app.portfolioengine.ui.components.FlowNode
import app.portfolioengine.ui.components.MoneyFlow
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SideChip
import app.portfolioengine.ui.components.Stat
import app.portfolioengine.ui.components.prettyDate
import org.json.JSONObject
import java.time.LocalDate

/** Tab 2: the trades, why each one, what it costs, and the order to do them in. */
@Composable
fun PlanTab(vm: MainViewModel, state: UiState, go: (String) -> Unit) {
    val d = state.check
    var marking by remember { mutableStateOf<JSONObject?>(null) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        Text("The plan", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 12.dp))
        if (d != null) Muted("As of ${prettyDate(d.str("asof"))}")
        BusyLine(state.checking)
        Spacer(Modifier.height(8.dp))
        if (d == null) {
            EmptyState("No plan yet", state.checkError ?: "The plan appears after the first check on the Today tab.")
            return@Column
        }
        val trades = d.objects("trades")
        val hold = d.obj("verdict").str("call") != "REBALANCE"
        if (trades.isEmpty()) {
            EmptyState("Nothing to do today", "Your portfolio already matches what the model wants, or every move costs more in tax and fees than it is expected to earn.")
        } else {
            if (hold) {
                AppCard {
                    Text("The call today is HOLD", style = MaterialTheme.typography.titleMedium)
                    Muted("These are the moves the model considered. Together they are not worth their cost today, so there is no need to place them.")
                }
                Spacer(Modifier.height(12.dp))
            }
            val timing = d.strings("timing")
            if (timing.isNotEmpty()) {
                AppCard {
                    Text("When to place them", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    Bullets(timing)
                    if (!hold && timing.any { it.contains("wait", ignoreCase = true) }) {
                        Spacer(Modifier.height(12.dp))
                        Muted("The waiting can be worked out from prices already seen, instead of from days still to come.")
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(onClick = { go(Routes.REPLAY) }) { Text("Skip the wait") }
                    }
                }
                Spacer(Modifier.height(12.dp))
            }
            val (sold, bought) = flowNodes(trades)
            if (sold.isNotEmpty() && bought.isNotEmpty()) {
                AppCard {
                    Text("Where the money moves", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(10.dp))
                    MoneyFlow(sold, bought)
                }
                Spacer(Modifier.height(12.dp))
            }
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                for (t in trades) TradeCard(t) { marking = t }
            }
        }

        val steps = d.objects("steps")
        if (trades.isNotEmpty() && steps.isNotEmpty()) {
            SectionTitle("Step by step")
            AppCard {
                steps.forEachIndexed { i, s ->
                    if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Disclosure(s.str("title"), leading = { StepNumber(i + 1) }) {
                        Muted(s.str("detail"))
                        val why = s.strings("why")
                        if (why.isNotEmpty()) {
                            Spacer(Modifier.height(8.dp))
                            Bullets(why)
                        }
                    }
                }
            }
        }

        val held = d.strings("blocked") + d.strings("deferred")
        val notes = d.strings("notes")
        if (held.isNotEmpty() || notes.isNotEmpty()) {
            SectionTitle("Also worth knowing")
            AppCard {
                if (held.isNotEmpty()) Disclosure("Moves held back", subtitle = "${held.size} considered and not taken") { Bullets(held) }
                if (held.isNotEmpty() && notes.isNotEmpty()) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                if (notes.isNotEmpty()) Disclosure("Notes on your holdings", subtitle = "${notes.size} note${if (notes.size == 1) "" else "s"}") { Bullets(notes) }
            }
        }

        if (d.bool("window_open")) {
            Spacer(Modifier.height(16.dp))
            AppCard {
                Text("Placed everything?", style = MaterialTheme.typography.titleMedium)
                Muted("Mark each trade as done above so your lots stay right, then close the waiting window.")
                Spacer(Modifier.height(10.dp))
                OutlinedButton(onClick = vm::closeWindow) { Text("Close the window") }
            }
        }
        Spacer(Modifier.height(24.dp))
    }

    marking?.let { t ->
        MarkDoneDialog(t, onDismiss = { marking = null }) { qty, price, date ->
            vm.mutate("apply_trade", jsonOf("symbol" to t.str("symbol"), "side" to t.str("side"), "qty" to qty, "price" to price, "date" to date), done = {
                vm.say("Recorded. Your lots are updated.")
            })
            marking = null
        }
    }
}

@Composable
private fun StepNumber(n: Int) {
    Text("$n", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary, modifier = Modifier.width(18.dp))
}

@Composable
private fun TradeCard(t: JSONObject, onDone: () -> Unit) {
    AppCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SideChip(t.str("side"))
            Spacer(Modifier.width(10.dp))
            Text(t.str("symbol"), style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Text(Fmt.inr(t.num("value")), style = MaterialTheme.typography.titleMedium)
        }
        Spacer(Modifier.height(6.dp))
        if (t.str("symbol") == "CASH") Muted("Park it in a liquid or arbitrage fund, or leave it in your bank sweep.")
        else Muted("${Fmt.qty(t.num("qty"))} units at about ₹${Fmt.price(t.num("price"))}")
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Stat("Fees", Fmt.inr(t.num("cost")), Modifier.weight(1f))
            Stat("Tax now", Fmt.inr(t.num("tax_now")), Modifier.weight(1f))
            Stat("Kind", kindLabel(t.str("kind")), Modifier.weight(1.2f))
        }
        Spacer(Modifier.height(6.dp))
        Disclosure("Why") {
            Bullets(t.strings("why"))
            val lots = t.objects("lots")
            if (lots.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Muted("Lots used, oldest first: " + lots.joinToString("; ") { "${Fmt.qty(it.num("qty"))} bought ${prettyDate(it.str("buy_date"))}" })
            }
        }
        if (t.str("symbol") != "CASH") {
            AppTextButton(onClick = onDone, modifier = Modifier.align(Alignment.End)) { Text("I placed this") }
        }
    }
}

/** Sells and buys of the plan as two columns with equal totals; cash absorbs whatever one side has over the other. Tax harvests sell and re-buy the same thing, so they move no money. */
private fun flowNodes(trades: List<JSONObject>): Pair<List<FlowNode>, List<FlowNode>> {
    val real = trades.filter { !it.str("kind").startsWith("harvest") }
    val sold = real.filter { it.str("side") == "sell" }.groupBy { it.str("symbol") }.map { (k, v) -> FlowNode(k, v.sumOf { it.num("value") }) }.sortedByDescending { it.value }.toMutableList()
    val bought = real.filter { it.str("side") == "buy" }.groupBy { it.str("symbol") }.map { (k, v) -> FlowNode(if (k == "CASH") "Cash" else k, v.sumOf { it.num("value") }) }.sortedByDescending { it.value }.toMutableList()
    val gap = sold.sumOf { it.value } - bought.sumOf { it.value }
    val floor = 0.01 * maxOf(sold.sumOf { it.value }, bought.sumOf { it.value })
    if (gap > floor) {
        val i = bought.indexOfFirst { it.label == "Cash" }
        if (i >= 0) bought[i] = FlowNode("Cash", bought[i].value + gap) else bought.add(FlowNode("Cash", gap))
    } else if (-gap > floor) {
        sold.add(FlowNode("Cash", -gap))
    }
    return sold to bought
}

private fun kindLabel(kind: String): String = when (kind) {
    "rebalance" -> "Rebalance"
    "risk_exit" -> "Cut risk"
    "harvest_gain" -> "Harvest gain"
    "harvest_loss" -> "Harvest loss"
    else -> kind.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

@Composable
private fun MarkDoneDialog(t: JSONObject, onDismiss: () -> Unit, onSave: (Double, Double, String) -> Unit) {
    var qty by remember { mutableStateOf(Fmt.qty(kotlin.math.floor(t.num("qty"))).replace(",", "")) }
    var price by remember { mutableStateOf(String.format(java.util.Locale.US, "%.2f", t.num("price"))) }
    var date by remember { mutableStateOf(LocalDate.now().toString()) }
    val q = qty.toDoubleOrNull()
    val p = price.toDoubleOrNull()
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("${if (t.str("side") == "sell") "Sold" else "Bought"} ${t.str("symbol")}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Muted("Enter what actually happened so the tax lots stay exact.")
                Spacer(Modifier.height(4.dp))
                NumberField(qty, { qty = it }, "Quantity")
                NumberField(price, { price = it }, "Price per unit, in rupees")
                DateField("Date", date, { date = it })
            }
        },
        confirmButton = { AppTextButton(enabled = q != null && q > 0 && p != null && p > 0, onClick = { onSave(q!!, p!!, date) }) { Text("Save") } },
        dismissButton = { AppTextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
