package app.portfolioengine.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.ui.components.AppButton
import app.portfolioengine.ui.components.AppTextButton
import app.portfolioengine.ui.components.AmountField
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.SubScreen
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate

/** Add one stock, ETF or mutual fund: search, then either units and price or just the amount. */
@Composable
fun AddHoldingScreen(vm: MainViewModel, fund: Boolean, onBack: () -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    var results by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var searching by remember { mutableStateOf(false) }
    var picked by remember { mutableStateOf<JSONObject?>(null) }
    var mode by rememberSaveable { mutableStateOf(if (fund) "amount" else "units") }
    var qty by rememberSaveable { mutableStateOf("") }
    var price by rememberSaveable { mutableStateOf("") }
    var amount by rememberSaveable { mutableStateOf("") }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    // search as you type, after a short pause
    LaunchedEffect(query, fund) {
        if (picked != null) return@LaunchedEffect
        if (query.trim().length < 2) {
            results = emptyList()
            return@LaunchedEffect
        }
        delay(350)
        searching = true
        val r = vm.call(if (fund) "search_funds" else "search_symbols", query.trim())
        results = ((r as? EngineResult.Ok)?.data as? JSONArray)?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } } ?: emptyList()
        error = (r as? EngineResult.Err)?.message
        searching = false
    }

    SubScreen(if (fund) "Add a mutual fund" else "Add a stock or ETF", onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            val p = picked
            if (p == null) {
                OutlinedTextField(
                    value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text(if (fund) "Fund name" else "Name or symbol") },
                    placeholder = { Text(if (fund) "parag parikh flexi" else "TCS, Nifty, Apple") },
                    leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                    supportingText = { Text(if (searching) "Searching" else if (fund) "Pick the exact plan you hold: direct or regular, growth or IDCW" else "Indian and US stocks and ETFs") },
                    keyboardOptions = KeyboardOptions(capitalization = if (fund) KeyboardCapitalization.None else KeyboardCapitalization.Characters, autoCorrectEnabled = false),
                )
                if (results.isNotEmpty()) {
                    AppCard {
                        results.forEachIndexed { i, r ->
                            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                            Column(Modifier.fillMaxWidth().clickable { picked = r }.padding(vertical = 12.dp)) {
                                if (fund) {
                                    Text(r.str("name"), style = MaterialTheme.typography.bodyLarge)
                                    if (r.bool("regular")) Muted("Regular plan")
                                } else {
                                    Text(r.str("symbol"), style = MaterialTheme.typography.titleMedium)
                                    Muted(r.str("name") + " · " + r.str("where"))
                                }
                            }
                        }
                    }
                }
                if (!fund && query.trim().length >= 2 && !searching) {
                    Spacer(Modifier.height(8.dp))
                    AppTextButton(onClick = { picked = JSONObject().put("symbol", query.trim().uppercase()).put("name", query.trim().uppercase()).put("currency", "INR").put("where", "NSE") }) {
                        Text("Use ${query.trim().uppercase()} as an NSE symbol")
                    }
                }
                if (error != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
            } else {
                val usd = p.str("currency") == "USD"
                AppCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(if (fund) p.str("name") else p.str("symbol"), style = MaterialTheme.typography.titleMedium)
                            if (!fund) Muted(p.str("name") + " · " + p.str("where"))
                        }
                        AppTextButton(onClick = {
                            picked = null
                            error = null
                        }) { Text("Change") }
                    }
                }
                Spacer(Modifier.height(16.dp))
                ChoiceRow(listOf("units" to if (fund) "Units and NAV" else "Quantity and price", "amount" to "Amount invested"), mode, { mode = it })
                Spacer(Modifier.height(8.dp))
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    DateField("Purchase date", date, { date = it })
                    if (mode == "units") {
                        NumberField(qty, { qty = it }, if (fund) "Units" else "Quantity")
                        NumberField(
                            price, { price = it }, if (fund) "NAV you bought at" else if (usd) "Price per share in dollars" else "Price per unit in rupees",
                            help = if (usd) "Converted to rupees at that day's USD/INR rate" else null,
                        )
                    } else {
                        AmountField(amount, { amount = it }, "Amount invested", help = if (fund) "Units are worked out from that day's NAV" else "Units are worked out from that day's closing price")
                    }
                }
                if (error != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(error!!, color = MaterialTheme.colorScheme.error)
                }
                Spacer(Modifier.height(16.dp))
                val q = qty.toDoubleOrNull()
                val px = price.toDoubleOrNull()
                val amt = Fmt.parseAmount(amount)
                val ready = if (mode == "units") q != null && q > 0 && px != null && px > 0 else amt != null && amt > 0
                AppButton(enabled = ready && !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                    busy = true
                    error = null
                    val o = JSONObject().put("buy_date", date)
                    if (fund) o.put("mf_code", p.str("code")).put("name", p.str("name")).put("symbol", "MF" + p.str("code"))
                    else {
                        o.put("symbol", p.str("symbol")).put("name", p.str("name"))
                        if (usd) o.put("currency", "USD")
                        val ticker = p.str("ticker")
                        if (ticker.isNotEmpty() && ticker != p.str("symbol") + ".NS") o.put("ticker", ticker)
                    }
                    if (mode == "units") o.put("qty", q).put("price", px) else o.put("amount_inr", amt)
                    scope.launch {
                        when (val r = vm.call("add_lot", o.toString())) {
                            is EngineResult.Err -> {
                                error = r.message
                                busy = false
                            }
                            is EngineResult.Ok -> {
                                vm.holdingsChanged()
                                vm.say("Added ${if (fund) "the fund" else p.str("symbol")}.")
                                onBack()
                            }
                        }
                    }
                }) { Text(if (busy) "Saving" else "Add") }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}
