package app.portfolioengine.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import app.portfolioengine.ui.components.AmountField
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.DropdownField
import app.portfolioengine.ui.components.EmptyState
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.Stat
import app.portfolioengine.ui.components.SubScreen
import app.portfolioengine.ui.components.prettyDate
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDate

/** Fixed deposits: worth today, after-tax yield, and what breaking one early would pay. */
@Composable
fun DepositsScreen(vm: MainViewModel, onBack: () -> Unit) {
    var view by remember { mutableStateOf<JSONObject?>(null) }
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    var adding by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { (vm.call("fds") as? EngineResult.Ok)?.let { view = it.obj } }
    fun save(payload: String) {
        scope.launch {
            when (val r = vm.call("save_fd", payload)) {
                is EngineResult.Err -> vm.say(r.message)
                is EngineResult.Ok -> {
                    view = r.obj
                    adding = false
                    editing = null
                    vm.holdingsChanged()
                }
            }
        }
    }
    SubScreen("Fixed deposits", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            val items = view.objects("items")
            if (items.isEmpty()) EmptyState("No deposits yet", "Add a deposit to see what it really pays after tax and what breaking it early would cost.")
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                for (d in items) {
                    AppCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(d.str("label"), style = MaterialTheme.typography.titleMedium)
                                Muted("Matures ${prettyDate(d.str("maturity"))}" + if (d.int("days_left") > 0) ", in ${d.int("days_left")} days" else "")
                            }
                            Text(Fmt.inr(d.num("value_today")), style = MaterialTheme.typography.titleMedium)
                        }
                        Spacer(Modifier.height(12.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Stat("Booked rate", Fmt.pct(d.num("rate"), 2), Modifier.weight(1f))
                            Stat("After tax", Fmt.pct(d.num("after_tax_yield"), 2), Modifier.weight(1f))
                            Stat("If broken today", Fmt.inrShort(d.num("break_value_today")), Modifier.weight(1.2f))
                        }
                        Disclosure("Tax and early closure") {
                            Muted(
                                "Interest this financial year ${Fmt.inr(d.num("interest_this_fy"))}, tax on it about ${Fmt.inr(d.num("tax_this_fy"))}. " +
                                    (if (d.bool("tds_likely")) "The bank will likely deduct TDS this year; it is a credit against your tax, not an extra tax. " else "") +
                                    d.str("penalty_note"),
                            )
                            Row {
                                TextButton(onClick = { editing = d }) { Text("Edit") }
                                TextButton(onClick = { removing = d }) { Text("Remove") }
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
            Button(onClick = { adding = true }, modifier = Modifier.fillMaxWidth()) { Text("Add a deposit") }
            Spacer(Modifier.height(32.dp))
        }
    }
    removing?.let { d ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("Remove ${d.str("label")}?") },
            text = { Text("This only removes it from the app. Nothing happens at the bank.") },
            confirmButton = {
                TextButton(onClick = {
                    save(jsonOf("index" to d.int("index"), "delete" to true))
                    removing = null
                }) { Text("Remove") }
            },
            dismissButton = { TextButton(onClick = { removing = null }) { Text("Cancel") } },
        )
    }
    if (adding || editing != null) {
        DepositDialog(view, editing, onDismiss = { adding = false; editing = null }, onSave = ::save)
    }
}

@Composable
private fun DepositDialog(view: JSONObject?, d: JSONObject?, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    val banks = view.objects("banks")
    var bank by remember { mutableStateOf(d?.str("bank_id") ?: banks.firstOrNull()?.str("id") ?: "other") }
    var principal by remember { mutableStateOf(d?.num("principal")?.toLong()?.toString() ?: "") }
    var rate by remember { mutableStateOf(d?.let { String.format(java.util.Locale.US, "%.2f", it.num("rate") * 100) } ?: "") }
    var start by remember { mutableStateOf(d?.str("start") ?: LocalDate.now().toString()) }
    var months by remember { mutableStateOf(d?.int("months")?.toString() ?: "12") }
    var payout by remember { mutableStateOf(d?.str("payout") ?: "cumulative") }
    var label by remember { mutableStateOf(d?.str("label") ?: "") }
    val ok = Fmt.parseAmount(principal) != null && (rate.toDoubleOrNull() ?: 0.0) > 0 && (months.toDoubleOrNull() ?: 0.0) >= 1
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (d == null) "Add a deposit" else "Edit deposit") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                DropdownField("Bank", banks.map { it.str("id") to it.str("name") }, bank, { bank = it })
                Muted(banks.firstOrNull { it.str("id") == bank }.str("where"))
                Spacer(Modifier.height(4.dp))
                AmountField(principal, { principal = it }, "Amount deposited")
                NumberField(rate, { rate = it }, "Interest rate", suffix = "% a year")
                DateField("Start date", start, { start = it })
                NumberField(months, { months = it }, "Tenure", suffix = "months")
                Text("Interest is paid", style = MaterialTheme.typography.labelLarge)
                ChoiceRow(listOf("cumulative" to "At maturity", "quarterly" to "Quarterly", "monthly" to "Monthly"), payout, { payout = it })
                OutlinedTextField(value = label, onValueChange = { label = it }, label = { Text("Short name (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            TextButton(enabled = ok, onClick = {
                onSave(
                    jsonOf(
                        "index" to d?.int("index"), "bank" to bank, "principal" to Fmt.parseAmount(principal), "rate" to rate.toDoubleOrNull(), "start" to start,
                        "months" to months.toDoubleOrNull(), "payout" to payout, "label" to label.ifBlank { null }, "senior" to (d?.bool("senior") ?: false),
                    ),
                )
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Investments the engine cannot trade but counts in your allocation. */
@Composable
fun OtherAssetsScreen(vm: MainViewModel, onBack: () -> Unit) {
    var view by remember { mutableStateOf<JSONObject?>(null) }
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    var adding by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { (vm.call("others") as? EngineResult.Ok)?.let { view = it.obj } }
    fun save(payload: String) {
        scope.launch {
            when (val r = vm.call("save_other", payload)) {
                is EngineResult.Err -> vm.say(r.message)
                is EngineResult.Ok -> {
                    view = r.obj
                    adding = false
                    editing = null
                    vm.holdingsChanged()
                }
            }
        }
    }
    SubScreen("Other assets", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Muted("EPF, PPF, NPS, gold, property, savings and anything else. The engine never trades these; it counts them when it checks your equity share and emergency fund.")
            Spacer(Modifier.height(12.dp))
            val items = view.objects("items")
            if (items.isEmpty()) EmptyState("Nothing here yet", "Add the rest of what you own for a full picture.")
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                for (o in items) {
                    AppCard(onClick = { editing = o }) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(o.str("name"), style = MaterialTheme.typography.titleMedium)
                                Muted(o.str("kind_label") + " · counted as " + o.str("cls").replace('_', ' '))
                            }
                            Text(Fmt.inr(o.num("value_inr")), style = MaterialTheme.typography.titleMedium)
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
            Button(onClick = { adding = true }, modifier = Modifier.fillMaxWidth()) { Text("Add an asset") }
            Spacer(Modifier.height(32.dp))
        }
    }
    if (adding || editing != null) {
        val o = editing
        val kinds = view.objects("kinds")
        var kind by remember(o) { mutableStateOf(o?.str("kind") ?: "epf") }
        var name by remember(o) { mutableStateOf(o?.str("name") ?: "") }
        var value by remember(o) { mutableStateOf(o?.num("value_inr")?.toLong()?.toString() ?: "") }
        AlertDialog(
            onDismissRequest = { adding = false; editing = null },
            title = { Text(if (o == null) "Add an asset" else "Edit asset") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    DropdownField("Kind", kinds.map { it.str("id") to it.str("label") }, kind, { kind = it })
                    Muted("Where to find it: " + kinds.firstOrNull { it.str("id") == kind }.str("where"))
                    Spacer(Modifier.height(4.dp))
                    OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Short name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    AmountField(value, { value = it }, "Value today")
                }
            },
            confirmButton = {
                TextButton(enabled = Fmt.parseAmount(value) != null, onClick = {
                    save(jsonOf("index" to o?.int("index"), "kind" to kind, "name" to name.ifBlank { null }, "value_inr" to Fmt.parseAmount(value)))
                }) { Text("Save") }
            },
            dismissButton = {
                Row {
                    if (o != null) TextButton(onClick = { save(jsonOf("index" to o.int("index"), "delete" to true)) }) { Text("Remove") }
                    TextButton(onClick = { adding = false; editing = null }) { Text("Cancel") }
                }
            },
        )
    }
}
