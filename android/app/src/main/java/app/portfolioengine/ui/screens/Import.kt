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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.portfolioengine.ImportState
import app.portfolioengine.MainViewModel
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.num
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.components.AppButton
import app.portfolioengine.ui.components.AppTextButton
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.Bullets
import app.portfolioengine.ui.components.ChoiceRow
import app.portfolioengine.ui.components.DateField
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.NumberField
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.SubScreen
import app.portfolioengine.ui.components.prettyDate
import org.json.JSONObject
import java.time.LocalDate

private val KIND_LABEL = mapOf(
    "tradebook" to "Trade history", "snapshot" to "Holdings list", "etrade" to "E*TRADE stock plan", "cas" to "Mutual fund statement",
    "holdings_yaml" to "Engine holdings file", "backup" to "App backup", "text" to "Typed list",
)

/**
 * One screen for every kind of import: pick (or type), answer at most one question, look at exactly what
 * would be added, confirm. Nothing is saved before the confirm.
 */
@Composable
fun ImportScreen(vm: MainViewModel, typed: Boolean, onBack: () -> Unit) {
    val st by vm.importState.collectAsStateWithLifecycle()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> if (uris.isNotEmpty()) vm.importFiles(uris) }
    val leave = {
        vm.importReset()
        onBack()
    }
    SubScreen(if (typed && st is ImportState.Idle) "Type or paste a list" else "Import", leave) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            when (val s = st) {
                is ImportState.Idle -> if (typed) TypedEntry(vm) else PickFiles { picker.launch(IMPORT_MIME) }
                is ImportState.Working -> Column(Modifier.fillMaxWidth().padding(top = 80.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(16.dp))
                    Text(s.label, style = MaterialTheme.typography.titleMedium)
                }
                is ImportState.Needs -> NeedsForm(s, vm)
                is ImportState.Preview -> PreviewView(s.data, vm)
                is ImportState.Failed -> {
                    Spacer(Modifier.height(24.dp))
                    Text("That did not work", style = MaterialTheme.typography.titleLarge)
                    Spacer(Modifier.height(8.dp))
                    Muted(s.message)
                    Spacer(Modifier.height(20.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        AppButton(onClick = { vm.importReset() }) { Text(if (typed) "Edit the list" else "Pick another file") }
                        OutlinedButton(onClick = leave) { Text("Close") }
                    }
                    if (!typed) {
                        SectionTitle("Where do I find my files?")
                        AppCard { FileGuides() }
                    }
                }
                is ImportState.Done -> {
                    Spacer(Modifier.height(40.dp))
                    Text("Imported", style = MaterialTheme.typography.headlineSmall)
                    Spacer(Modifier.height(8.dp))
                    Muted("${s.lots} lot${if (s.lots == 1) "" else "s"} saved. The check is running again with the new holdings.")
                    Spacer(Modifier.height(20.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        AppButton(onClick = leave) { Text("Done") }
                        if (!typed) OutlinedButton(onClick = {
                            vm.importReset()
                            picker.launch(IMPORT_MIME)
                        }) { Text("Import another") }
                    }
                }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun PickFiles(pick: () -> Unit) {
    Spacer(Modifier.height(8.dp))
    Muted("Pick one file, or several of the same kind (for example a tradebook for each year). The app works out what it is and shows you what it found before anything is saved.")
    Spacer(Modifier.height(16.dp))
    AppButton(onClick = pick, modifier = Modifier.fillMaxWidth()) { Text("Choose files") }
    SectionTitle("Where do I find my files?")
    AppCard { FileGuides() }
    Spacer(Modifier.height(12.dp))
    Muted("Statements are read on this phone, turned into tax lots, and the copy is deleted. Nothing is uploaded.")
}

@Composable
private fun TypedEntry(vm: MainViewModel) {
    var text by rememberSaveable { mutableStateOf("") }
    Spacer(Modifier.height(8.dp))
    Muted("One holding per line. Either quantity and price, or just the amount you invested. Add the date if you know it.")
    Spacer(Modifier.height(12.dp))
    OutlinedTextField(
        value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth().heightIn(min = 180.dp),
        textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
        placeholder = { Text("NIFTYBEES 5 lakh 14/08/2024\nTCS 12 3900 2024-09-16\nGOLDBEES 200 62.5", fontFamily = FontFamily.Monospace) },
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, autoCorrectEnabled = false),
    )
    Spacer(Modifier.height(12.dp))
    AppButton(enabled = text.isNotBlank(), onClick = { vm.importTyped(text) }, modifier = Modifier.fillMaxWidth()) { Text("Review") }
    Spacer(Modifier.height(12.dp))
    Muted("Use the exchange symbol (TCS, NIFTYBEES). Lines without a date use today. Add $ after a US price to convert from dollars.")
}

@Composable
private fun NeedsForm(s: ImportState.Needs, vm: MainViewModel) {
    var password by rememberSaveable { mutableStateOf("") }
    var ticker by rememberSaveable { mutableStateOf("") }
    var rate by rememberSaveable { mutableStateOf("") }
    var age by rememberSaveable { mutableStateOf("old") }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().minusMonths(18).toString()) }
    Spacer(Modifier.height(8.dp))
    Text(KIND_LABEL[s.kind] ?: "One more thing", style = MaterialTheme.typography.titleLarge)
    Spacer(Modifier.height(6.dp))
    Muted(s.message)
    Spacer(Modifier.height(16.dp))
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if ("password" in s.needs) {
            OutlinedTextField(
                value = password, onValueChange = { password = it }, label = { Text("Statement password") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            )
        }
        if ("ticker" in s.needs) {
            OutlinedTextField(
                value = ticker, onValueChange = { ticker = it.uppercase().filter { c -> c.isLetterOrDigit() || c == '.' } }, label = { Text("Stock ticker") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
            )
        }
        if ("usd_inr" in s.needs) NumberField(rate, { rate = it }, "USD/INR rate", help = "Rupees per dollar, for example 88.5")
        if ("approx_date" in s.needs) {
            ChoiceRow(listOf("old" to "Over a year ago", "new" to "Within the last year", "date" to "Pick a date"), age, {
                age = it
                if (it == "old") date = LocalDate.now().minusMonths(18).toString()
                if (it == "new") date = LocalDate.now().minusMonths(4).toString()
            })
            if (age == "date") DateField("Purchase date", date, { date = it })
        }
    }
    Spacer(Modifier.height(16.dp))
    val ready = ("password" !in s.needs || password.isNotEmpty()) && ("ticker" !in s.needs || ticker.isNotEmpty()) && ("usd_inr" !in s.needs || (rate.toDoubleOrNull() ?: 0.0) > 0)
    AppButton(enabled = ready, modifier = Modifier.fillMaxWidth(), onClick = {
        vm.importAnswer(
            buildMap {
                if ("password" in s.needs) put("password", password)
                if ("ticker" in s.needs) put("ticker", ticker)
                if ("usd_inr" in s.needs) put("usd_inr", rate.toDoubleOrNull())
                if ("approx_date" in s.needs) put("approx_date", date)
            },
        )
    }) { Text("Continue") }
}

@Composable
private fun PreviewView(d: JSONObject, vm: MainViewModel) {
    val rows = d.objects("by_symbol")
    val replaces = d.strings("replaces")
    val replaceAll = d.bool("replace_all")
    var append by rememberSaveable { mutableStateOf(false) }
    Spacer(Modifier.height(8.dp))
    Text(KIND_LABEL[d.str("kind")] ?: "Import", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    Text("${d.int("lots")} lot${if (d.int("lots") == 1) "" else "s"} in ${rows.size} holding${if (rows.size == 1) "" else "s"}", style = MaterialTheme.typography.headlineSmall)
    Muted("Cost ${Fmt.inr(d.num("total_cost"))}. Nothing is saved yet.")
    Spacer(Modifier.height(12.dp))
    val warnings = d.strings("warnings")
    if (warnings.isNotEmpty()) {
        AppCard {
            Text("Worth a look", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Bullets(warnings)
        }
        Spacer(Modifier.height(12.dp))
    }
    AppCard {
        rows.forEachIndexed { i, r ->
            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(Modifier.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(r.str("symbol"), style = MaterialTheme.typography.titleMedium)
                    val name = r.str("name")
                    if (name.isNotEmpty() && name != r.str("symbol")) Muted(name)
                    Muted(
                        (if (r.num("qty") > 0) "${Fmt.qty(r.num("qty"))} units · " else "") + "${r.int("lots")} lot${if (r.int("lots") == 1) "" else "s"} · " +
                            if (r.str("first") == r.str("last")) prettyDate(r.str("first")) else "${prettyDate(r.str("first"))} to ${prettyDate(r.str("last"))}",
                    )
                }
                Text(Fmt.inr(r.num("cost")), style = MaterialTheme.typography.titleMedium)
            }
        }
    }
    Spacer(Modifier.height(12.dp))
    when {
        replaceAll -> Muted("This replaces everything in the app with the contents of the file. A copy of the current holdings is kept as a backup file inside the app.")
        replaces.isNotEmpty() -> {
            Muted("You already hold ${replaces.joinToString(", ")}. Their existing lots are replaced so nothing is counted twice.")
            AppTextButton(onClick = { append = !append }) { Text(if (append) "Adding on top instead. Tap to replace." else "Add on top of the existing lots instead") }
        }
        else -> {}
    }
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        AppButton(onClick = { vm.importCommit(if (append) "append" else "replace_symbols") }, modifier = Modifier.weight(1f)) { Text(if (replaceAll) "Replace and import" else "Import") }
        OutlinedButton(onClick = { vm.importReset() }) { Text("Cancel") }
    }
}
