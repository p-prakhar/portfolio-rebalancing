package app.portfolioengine.ui.screens

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
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.num
import app.portfolioengine.model.obj
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.components.ActionBar
import app.portfolioengine.ui.components.AmountField
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SubScreen
import kotlinx.coroutines.launch
import org.json.JSONObject

private val MONEY = listOf(
    "monthly_expenses_inr", "health_cover_inr", "term_cover_inr", "credit_card_limit_inr", "gross_salary_inr", "rsu_perquisite_inr",
    "other_income_inr", "deductions_inr", "carried_st_loss_inr", "carried_lt_loss_inr",
)

/** You and your income. Never changes the trades by itself: it sets the tax slab and the guardrails. */
@Composable
fun ProfileScreen(vm: MainViewModel, onBack: () -> Unit) {
    var view by remember { mutableStateOf<JSONObject?>(null) }
    val f = remember { mutableStateMapOf<String, String>() }
    var risk by remember { mutableStateOf("moderate") }
    var regime by remember { mutableStateOf("new") }
    var backups by remember { mutableStateOf(false) }
    var rsu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun load(v: JSONObject) {
        view = v
        val p = v.obj("profile")
        f["age"] = p.int("age", 30).toString()
        f["horizon_years"] = p.int("horizon_years", 15).toString()
        f["employer_ticker"] = p.str("employer_ticker")
        for (k in MONEY) f[k] = p.num(k).let { if (it > 0) it.toLong().toString() else "" }
        risk = p.str("risk", "moderate")
        regime = p.str("tax_regime", "new")
        backups = p.bool("count_backups")
        rsu = p.bool("has_rsu")
    }
    LaunchedEffect(Unit) { (vm.call("profile") as? EngineResult.Ok)?.let { load(it.obj) } }

    val saveNow: () -> Unit = {
                val o = JSONObject()
                o.put("age", f["age"]?.toDoubleOrNull() ?: 30.0).put("horizon_years", f["horizon_years"]?.toDoubleOrNull() ?: 15.0)
                o.put("risk", risk).put("tax_regime", regime).put("count_backups", backups).put("has_rsu", rsu)
                o.put("employer_ticker", if (rsu) f["employer_ticker"].orEmpty() else "")
                for (k in MONEY) o.put(k, Fmt.parseAmount(f[k].orEmpty()) ?: 0.0)
                scope.launch {
                    when (val r = vm.call("save_profile", o.toString())) {
                        is EngineResult.Err -> error = r.message
                        is EngineResult.Ok -> {
                            vm.profileSaved()
                            vm.say("Profile saved.")
                            onBack()
                        }
                    }
                }
            }
    SubScreen("Profile and income", onBack, bottomBar = { if (view != null) ActionBar("Save", error = error, onClick = saveNow) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            val v = view
            if (v == null) {
                Muted("Loading")
                return@Column
            }
            Muted("These never change the trades directly. They set your tax slab and the limits the plan is checked against. Leave anything you do not know empty.")
            SectionTitle("You")
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                NumberField(f["age"].orEmpty(), { f["age"] = it }, "Age", Modifier.weight(1f))
                NumberField(f["horizon_years"].orEmpty(), { f["horizon_years"] = it }, "Years until you need it", Modifier.weight(1.4f))
            }
            Text("Risk appetite", style = MaterialTheme.typography.labelLarge)
            ChoiceRow(listOf("conservative" to "Conservative", "moderate" to "Moderate", "aggressive" to "Aggressive"), risk, { risk = it })
            Muted("Equity guide for you: ${Fmt.pct(v.num("equity_cap"), 0)} of everything you own.")

            SectionTitle("Safety net")
            Money(f, "monthly_expenses_inr", "Monthly expenses", "Used for the emergency fund check")
            Money(f, "health_cover_inr", "Health insurance cover", "Employer group cover plus your own")
            Money(f, "term_cover_inr", "Term life cover", null)
            Money(f, "credit_card_limit_inr", "Total credit card limit", null)
            ToggleRow("Count my backups", "Keep a smaller cash buffer because of insurance and card limits", backups) { backups = it }
            Muted("Cash buffer target: ${v.int("emergency_months")} months of expenses. ${v.str("emergency_note")}")

            SectionTitle("Income this financial year")
            Text("Tax regime", style = MaterialTheme.typography.labelLarge)
            ChoiceRow(listOf("new" to "New", "old" to "Old"), regime, { regime = it })
            Spacer(Modifier.height(8.dp))
            Money(f, "gross_salary_inr", "Gross salary, without RSUs", "Form 16 Part B, or 12 times the monthly gross")
            Money(f, "rsu_perquisite_inr", "RSU or ESPP income taxed as salary", "Payslip stock perquisite lines")
            Money(f, "other_income_inr", "Other income", "Interest, dividends and rent, from the AIS")
            if (regime == "old") Money(f, "deductions_inr", "Deductions", "80C, 80D, HRA, home loan interest")
            Money(f, "carried_st_loss_inr", "Short-term capital loss carried forward", "Last ITR, Schedule CFL")
            Money(f, "carried_lt_loss_inr", "Long-term capital loss carried forward", "Last ITR, Schedule CFL")
            if (v.str("tax_note").isNotEmpty()) Muted(v.str("tax_note"))
            AppCard(Modifier.padding(top = 8.dp)) {
                Disclosure("Where to find these numbers") {
                    val items = v.objects("income_where_items")
                    if (items.isEmpty()) {
                        Text(v.str("income_where"), style = MaterialTheme.typography.bodyMedium)
                    } else {
                        // a label with its sources underneath: columns do not fit a phone
                        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            for (item in items) {
                                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                    Text(item.str("label"), style = MaterialTheme.typography.titleSmall)
                                    for (line in item.strings("lines")) Muted(line)
                                }
                            }
                        }
                    }
                }
            }

            SectionTitle("Employer stock")
            ToggleRow("I get RSUs or ESPP from a US-listed employer", "The stock plan account is treated as sell only", rsu) { rsu = it }
            if (rsu) {
                OutlinedTextField(
                    value = f["employer_ticker"].orEmpty(), onValueChange = { f["employer_ticker"] = it.uppercase() }, label = { Text("Employer ticker") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                )
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun Money(f: MutableMap<String, String>, key: String, label: String, help: String?) {
    AmountField(f[key].orEmpty(), { f[key] = it }, label, help = help)
}

@Composable
fun ToggleRow(title: String, body: String?, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (body != null) Muted(body)
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
