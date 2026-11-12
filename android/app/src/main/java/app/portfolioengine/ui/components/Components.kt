package app.portfolioengine.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.portfolioengine.model.Fmt
import app.portfolioengine.ui.theme.LocalTokens
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

val ScreenPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)

@Composable
fun AppCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    val shape = MaterialTheme.shapes.medium
    val border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    if (onClick != null) {
        Surface(onClick = onClick, modifier = modifier.fillMaxWidth(), shape = shape, color = MaterialTheme.colorScheme.surfaceContainerLow, border = border) {
            Column(Modifier.padding(16.dp), content = content)
        }
    } else {
        Surface(modifier = modifier.fillMaxWidth(), shape = shape, color = MaterialTheme.colorScheme.surfaceContainerLow, border = border) {
            Column(Modifier.padding(16.dp), content = content)
        }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = modifier.padding(top = 20.dp, bottom = 8.dp))
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = modifier)
}

@Composable
fun Stat(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** BUY and SELL always wear their own colours. */
@Composable
fun SideChip(side: String) {
    val t = LocalTokens.current
    val buy = side.equals("buy", ignoreCase = true)
    Pill(side.uppercase(Locale.US), if (buy) t.buy else t.sell, if (buy) t.buyContainer else t.sellContainer)
}

@Composable
fun Pill(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    Text(
        text, color = fg, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold,
        modifier = modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

/** ok, warn or info marker with a text alternative for screen readers. */
@Composable
fun LevelDot(level: String) {
    val t = LocalTokens.current
    val c = when (level) {
        "ok" -> t.buy
        "warn", "bad" -> t.warn
        else -> MaterialTheme.colorScheme.outline
    }
    Box(Modifier.size(10.dp).clip(CircleShape).background(c).semantics { contentDescription = if (level == "ok") "Fine" else if (level == "warn") "Needs attention" else "Note" })
}

/** A row that opens to show detail: the app's way of keeping screens light. */
@Composable
fun Disclosure(title: String, modifier: Modifier = Modifier, subtitle: String? = null, startOpen: Boolean = false, leading: (@Composable () -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    var open by rememberSaveable(title) { mutableStateOf(startOpen) }
    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().clip(MaterialTheme.shapes.small).clickable(role = Role.Button) { open = !open }.heightIn(min = 48.dp).padding(vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (leading != null) {
                leading()
                Spacer(Modifier.width(12.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge)
                if (subtitle != null) Muted(subtitle)
            }
            Icon(if (open) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, contentDescription = if (open) "Hide details" else "Show details", tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        AnimatedVisibility(open) {
            Column(Modifier.padding(top = 4.dp, bottom = 10.dp), content = content)
        }
    }
}

@Composable
fun Bullets(lines: List<String>, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        for (l in lines) {
            Row {
                Text("•", Modifier.width(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(l.replace("**", ""), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
fun <T> ChoiceRow(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((value, label) in options) {
            FilterChip(selected = value == selected, onClick = { onSelect(value) }, label = { Text(label) })
        }
    }
}

/** Rupee amount. Accepts "5 lakh", "2.5cr", "45k" and shows what it understood. */
@Composable
fun AmountField(value: String, onValue: (String) -> Unit, label: String, modifier: Modifier = Modifier, help: String? = null) {
    val parsed = Fmt.parseAmount(value)
    OutlinedTextField(
        value = value, onValueChange = onValue, label = { Text(label) }, singleLine = true, modifier = modifier.fillMaxWidth(),
        prefix = { Text("₹") },
        isError = value.isNotBlank() && parsed == null,
        supportingText = {
            Text(
                when {
                    value.isNotBlank() && parsed == null -> "Enter a number, for example 500000 or 5 lakh"
                    parsed != null && parsed >= 1000 -> listOfNotNull(Fmt.inr(parsed), help).joinToString(" · ")
                    else -> help ?: ""
                },
            )
        },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
    )
}

@Composable
fun NumberField(value: String, onValue: (String) -> Unit, label: String, modifier: Modifier = Modifier, help: String? = null, suffix: String? = null) {
    OutlinedTextField(
        value = value, onValueChange = { s -> onValue(s.filter { it.isDigit() || it == '.' }) }, label = { Text(label) }, singleLine = true,
        modifier = modifier.fillMaxWidth(), supportingText = help?.let { { Text(it) } }, suffix = suffix?.let { { Text(it) } },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
    )
}

private val Pretty = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.US)

fun prettyDate(iso: String): String = try {
    LocalDate.parse(iso.take(10)).format(Pretty)
} catch (e: Exception) {
    iso
}

/** A date shown in words; tapping opens the calendar. Value is ISO (2024-08-14). */
@Composable
fun DateField(label: String, iso: String, onChange: (String) -> Unit, modifier: Modifier = Modifier, help: String? = null) {
    var open by remember { mutableStateOf(false) }
    Box(modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = if (iso.isBlank()) "" else prettyDate(iso), onValueChange = {}, readOnly = true, label = { Text(label) }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), supportingText = help?.let { { Text(it) } },
            trailingIcon = { Icon(Icons.Filled.CalendarMonth, contentDescription = null) },
        )
        // the whole field is the button
        Box(Modifier.matchParentSize().clip(MaterialTheme.shapes.small).clickable(role = Role.Button, onClickLabel = "Choose $label") { open = true })
    }
    if (open) {
        val initial = try {
            LocalDate.parse(iso).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        } catch (e: Exception) {
            null
        }
        val state = rememberDatePickerState(initialSelectedDateMillis = initial)
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state = state) }
    }
}

/** A labelled value that opens a list of choices. */
@Composable
fun <T> DropdownField(label: String, options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    var open by remember { mutableStateOf(false) }
    Box(modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = options.firstOrNull { it.first == selected }?.second ?: "", onValueChange = {}, readOnly = true, label = { Text(label) }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), trailingIcon = { Icon(Icons.Filled.ExpandMore, contentDescription = null) },
        )
        Box(Modifier.matchParentSize().clip(MaterialTheme.shapes.small).clickable(role = Role.DropdownList, onClickLabel = "Choose $label") { open = true })
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, modifier = Modifier.widthIn(min = 240.dp)) {
            for ((value, text) in options) {
                DropdownMenuItem(text = { Text(text) }, onClick = {
                    onSelect(value)
                    open = false
                })
            }
        }
    }
}

/** One horizontal bar split by share, with a legend underneath. Segments are (label, value). */
@Composable
fun AllocationBar(segments: List<Pair<String, Double>>, modifier: Modifier = Modifier) {
    val colors = LocalTokens.current.series
    val total = segments.sumOf { it.second }.takeIf { it > 0 } ?: return
    val shown = segments.filter { it.second / total >= 0.005 }
    Column(modifier) {
        Row(Modifier.fillMaxWidth().height(14.dp).clip(RoundedCornerShape(7.dp)), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
            shown.forEachIndexed { i, (_, v) ->
                Box(Modifier.weight((v / total).toFloat().coerceAtLeast(0.005f)).fillMaxSize().background(colors[i.coerceAtMost(colors.lastIndex)]))
            }
        }
        Spacer(Modifier.height(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            shown.forEachIndexed { i, (label, v) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp).clip(CircleShape).background(colors[i.coerceAtMost(colors.lastIndex)]))
                    Spacer(Modifier.width(6.dp))
                    Text("$label ${Fmt.pct(v / total, 0)}", style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable
fun EmptyState(title: String, body: String, modifier: Modifier = Modifier, action: String? = null, onAction: (() -> Unit)? = null) {
    Column(modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(title, style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(8.dp))
        Muted(body)
        if (action != null && onAction != null) {
            Spacer(Modifier.height(20.dp))
            Button(onClick = onAction) { Text(action) }
        }
    }
}

@Composable
fun BusyLine(visible: Boolean) {
    if (visible) LinearProgressIndicator(Modifier.fillMaxWidth().height(3.dp)) else Spacer(Modifier.height(3.dp))
}

/** Frame for every screen that is not one of the four tabs. */
@Composable
fun SubScreen(title: String, onBack: () -> Unit, actions: @Composable RowScope.() -> Unit = {}, bottomBar: @Composable () -> Unit = {}, content: @Composable (PaddingValues) -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } },
                actions = actions,
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = bottomBar,
        containerColor = MaterialTheme.colorScheme.background,
        content = content,
    )
}

fun sleeveLabel(sleeve: String): String = when (sleeve) {
    "india_equity" -> "India equity"
    "global_equity" -> "Global equity"
    "gold" -> "Gold"
    "cash" -> "Cash"
    "bonds" -> "Bonds"
    "commodity" -> "Commodities"
    "metals" -> "Metals"
    "semis" -> "Semiconductors"
    "debt" -> "Debt"
    else -> sleeve.replace('_', ' ').replaceFirstChar { it.uppercase() }
}
