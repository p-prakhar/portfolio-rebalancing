package app.portfolioengine.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.clickable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.UiState
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.numOrNull
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.AmountField
import app.portfolioengine.ui.components.AppTextButton
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.EmptyState
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.prettyDate
import app.portfolioengine.ui.theme.LocalTokens
import org.json.JSONObject

/** Tab 3: what you own, lot by lot, and every way to add more. */
@Composable
fun PortfolioTab(vm: MainViewModel, state: UiState, go: (String) -> Unit) {
    val h = state.holdings
    val check = state.check
    var adding by remember { mutableStateOf(false) }
    var editLot by remember { mutableStateOf<JSONObject?>(null) }
    var deleteLot by remember { mutableStateOf<JSONObject?>(null) }
    var editCash by remember { mutableStateOf(false) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            vm.importFiles(uris)
            go(Routes.IMPORT)
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Text("Portfolio", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 12.dp))
            val lots = h.objects("lots")
            // value and gain per symbol come from the last check; cost comes from the lots themselves
            val valued = check.objects("holdings").groupBy { it.str("symbol") }
            val nav = check?.num("nav")
            if (nav != null) Muted("Worth about ${Fmt.inrShort(nav)} at the last check")
            Spacer(Modifier.height(12.dp))

            if (lots.isEmpty()) {
                EmptyState("No holdings yet", "Add what you own to get a plan.", action = "Add holdings") { adding = true }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    for ((symbol, group) in lots.groupBy { it.str("symbol") }.entries.sortedByDescending { e -> e.value.sumOf { it.num("cost") } }) {
                        SymbolCard(symbol, group, valued[symbol].orEmpty(), onEdit = { editLot = it }, onDelete = { deleteLot = it })
                    }
                }
            }

            SectionTitle("Cash and accounts")
            AppCard {
                NavRow("Cash ready to invest", Fmt.inr(h?.num("cash_inr") ?: 0.0)) { editCash = true }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                NavRow("Fixed deposits", countLabel(check.objects("fds").size, "deposit")) { go(Routes.DEPOSITS) }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                NavRow("Other assets", "EPF, PPF, NPS, gold, property") { go(Routes.OTHERS) }
            }

            val mfs = check.objects("mfs")
            if (mfs.isNotEmpty()) {
                SectionTitle("Your mutual funds")
                AppCard {
                    mfs.forEachIndexed { i, m ->
                        if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Disclosure(m.str("name"), subtitle = Fmt.inr(m.num("value")) + if (m.bool("regular")) " · regular plan" else " · direct plan") {
                            if (m.bool("regular") && m.numOrNull("gap") != null) {
                                Muted(
                                    "The regular plan gave up ${Fmt.pct(m.num("gap"), 2)} a year against the direct plan, about ${Fmt.inr(m.num("yearly_cost"))} a year at today's value. " +
                                        "Switching now costs about ${Fmt.inr(m.num("switch_tax"))} in tax" +
                                        (if (m.num("exit_load_est") > 0) " plus about ${Fmt.inr(m.num("exit_load_est"))} exit load" else "") +
                                        (m.numOrNull("breakeven_years")?.let { " and pays back in ${String.format(java.util.Locale.US, "%.1f", it)} years." } ?: "."),
                                )
                            } else if (m.bool("regular")) {
                                Muted("Regular plan. No direct twin was found to compare against.")
                            } else {
                                Muted("Direct plan: no distributor commission inside the fund. Gain so far ${Fmt.signedInr(m.num("gain"))}.")
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(120.dp))
        }
        ExtendedFloatingActionButton(
            onClick = { adding = true }, icon = { Icon(Icons.Filled.Add, contentDescription = null) }, text = { Text("Add") },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
        )
    }

    if (adding) {
        ModalBottomSheet(onDismissRequest = { adding = false }) {
            Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
                Text("Add to your portfolio", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
                SheetRow("From a broker or app, step by step", "Zerodha, Groww, Upstox, E*TRADE and others") { adding = false; go(Routes.SOURCES) }
                SheetRow("Import a file", "Tradebook, holdings export, E*TRADE, backup") { adding = false; picker.launch(IMPORT_MIME) }
                SheetRow("Type or paste a list", "One holding per line") { adding = false; go(Routes.IMPORT_TYPED) }
                SheetRow("A stock or ETF", "Search, then enter what you paid") { adding = false; go(Routes.ADD) }
                SheetRow("A mutual fund", "Search the fund, then the amount and date") { adding = false; go(Routes.ADD_FUND) }
                SheetRow("A fixed deposit", "Bank, amount, rate and tenure") { adding = false; go(Routes.DEPOSITS) }
                SheetRow("Another asset", "EPF, PPF, NPS, gold, property, savings") { adding = false; go(Routes.OTHERS) }
            }
        }
    }

    editLot?.let { lot ->
        LotDialog(lot, onDismiss = { editLot = null }) { payload ->
            vm.mutate("update_lot", lot.int("index"), payload)
            editLot = null
        }
    }
    deleteLot?.let { lot ->
        AlertDialog(
            onDismissRequest = { deleteLot = null },
            title = { Text("Remove this lot?") },
            text = { Text("${lot.str("symbol")} bought ${prettyDate(lot.str("buy_date"))}. Use this to fix a mistake. If you sold it, record the sale from the Plan tab instead so the gain is counted.") },
            confirmButton = {
                AppTextButton(onClick = {
                    vm.mutate("delete_lot", lot.int("index"))
                    deleteLot = null
                }) { Text("Remove") }
            },
            dismissButton = { AppTextButton(onClick = { deleteLot = null }) { Text("Cancel") } },
        )
    }
    if (editCash) {
        var cash by remember { mutableStateOf(Fmt.grouped((h?.num("cash_inr") ?: 0.0).toLong()).replace(",", "")) }
        AlertDialog(
            onDismissRequest = { editCash = false },
            title = { Text("Cash ready to invest") },
            text = { AmountField(cash, { cash = it }, "Amount", help = "Money in the broker or bank that this portfolio can use") },
            confirmButton = {
                AppTextButton(enabled = Fmt.parseAmount(cash) != null, onClick = {
                    vm.mutate("set_account", jsonOf("cash_inr" to Fmt.parseAmount(cash)))
                    editCash = false
                }) { Text("Save") }
            },
            dismissButton = { AppTextButton(onClick = { editCash = false }) { Text("Cancel") } },
        )
    }
}

private fun countLabel(n: Int, noun: String) = if (n == 0) "None yet" else "$n $noun${if (n == 1) "" else "s"}"

@Composable
private fun NavRow(title: String, value: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Muted(value)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun SheetRow(title: String, body: String, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title) }, supportingContent = { Text(body) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.clickable(onClick = onClick).padding(horizontal = 8.dp),
    )
}

@Composable
private fun SymbolCard(symbol: String, lots: List<JSONObject>, valued: List<JSONObject>, onEdit: (JSONObject) -> Unit, onDelete: (JSONObject) -> Unit) {
    val t = LocalTokens.current
    val cost = lots.sumOf { it.num("cost") }
    val value = valued.sumOf { it.num("value") }.takeIf { valued.isNotEmpty() }
    val gain = valued.sumOf { it.num("gain") }
    val qty = lots.mapNotNull { it.numOrNull("qty") }.sum()
    val name = lots.first().str("name")
    AppCard {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Text(symbol, style = MaterialTheme.typography.titleMedium)
                if (name.isNotEmpty() && name != symbol) Muted(name)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(Fmt.inr(value ?: cost), style = MaterialTheme.typography.titleMedium)
                if (value != null) Text(Fmt.signedInr(gain), style = MaterialTheme.typography.bodyMedium, color = if (gain >= 0) t.buy else t.sell)
                else Muted("at cost")
            }
        }
        Disclosure(if (qty > 0) "${Fmt.qty(qty)} units in ${lots.size} lot${if (lots.size == 1) "" else "s"}" else "${lots.size} lot${if (lots.size == 1) "" else "s"}, units set at the next check") {
            for (lot in lots) {
                val term = valued.firstOrNull { it.str("buy_date") == lot.str("buy_date") }?.str("term").orEmpty()
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f).padding(vertical = 6.dp)) {
                        Text(prettyDate(lot.str("buy_date")), style = MaterialTheme.typography.bodyLarge)
                        val q = lot.numOrNull("qty")
                        Muted(
                            (if (q != null) "${Fmt.qty(q)} at ₹${Fmt.price(lot.num("price"))}" else "${Fmt.inr(lot.num("amount_inr"))} invested") +
                                (if (term.isNotEmpty()) " · $term" else ""),
                        )
                    }
                    IconButton(onClick = { onEdit(lot) }) { Icon(Icons.Filled.Edit, contentDescription = "Edit this lot") }
                    IconButton(onClick = { onDelete(lot) }) { Icon(Icons.Filled.Delete, contentDescription = "Remove this lot") }
                }
            }
        }
    }
}

@Composable
private fun LotDialog(lot: JSONObject, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    val amountOnly = lot.numOrNull("qty") == null
    var qty by remember { mutableStateOf(lot.numOrNull("qty")?.let { Fmt.qty(it).replace(",", "") } ?: "") }
    var price by remember { mutableStateOf(lot.numOrNull("price")?.toString() ?: "") }
    var amount by remember { mutableStateOf(lot.numOrNull("amount_inr")?.toLong()?.toString() ?: "") }
    var date by remember { mutableStateOf(lot.str("buy_date")) }
    val valid = if (amountOnly && qty.isBlank()) Fmt.parseAmount(amount) != null else (qty.toDoubleOrNull() ?: 0.0) > 0 && (price.toDoubleOrNull() ?: 0.0) > 0
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit ${lot.str("symbol")} lot") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                DateField("Purchase date", date, { date = it })
                NumberField(qty, { qty = it }, "Quantity")
                NumberField(price, { price = it }, "Cost per unit, in rupees", help = "For US shares: dollars times USD/INR on that day")
                if (amountOnly) AmountField(amount, { amount = it }, "Or the amount invested", help = "Used when quantity is empty")
            }
        },
        confirmButton = {
            AppTextButton(enabled = valid, onClick = {
                onSave(
                    if (qty.isNotBlank() && price.isNotBlank()) jsonOf("symbol" to lot.str("symbol"), "buy_date" to date, "qty" to qty.toDouble(), "price" to price.toDouble())
                    else jsonOf("symbol" to lot.str("symbol"), "buy_date" to date, "amount_inr" to Fmt.parseAmount(amount)),
                )
            }) { Text("Save") }
        },
        dismissButton = { AppTextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
