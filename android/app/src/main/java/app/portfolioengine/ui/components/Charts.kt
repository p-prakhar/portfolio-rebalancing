package app.portfolioengine.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.portfolioengine.model.Fmt
import app.portfolioengine.ui.theme.LocalTokens
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

// Charts drawn by hand on a Canvas so the app carries no chart library. Shared rules: 2dp lines, recessive hairline
// grid, text in text colours (never the series colour), a legend that doubles as the readout, and touch to read a day.

data class ChartLine(val name: String, val color: Color, val values: List<Double>, val dashed: Boolean = false)

data class ChartLayer(val name: String, val color: Color, val values: List<Double>)

/** The fixed colour slot of each sleeve, so India equity is the same colour on every chart. Order matches the validated palette. */
private val SLEEVE_SLOTS = listOf("india_equity", "global_equity", "cash", "gold", "commodity", "metals", "bonds", "semis")

fun sleeveSlot(sleeve: String): Int {
    val id = if (sleeve == "debt") "bonds" else sleeve
    val i = SLEEVE_SLOTS.indexOf(id)
    return if (i >= 0) i else SLEEVE_SLOTS.indexOfFirst { sleeveLabel(it) == sleeve }
}

@Composable
fun sleeveColor(sleeve: String): Color {
    val slot = sleeveSlot(sleeve)
    return if (slot >= 0) LocalTokens.current.series[slot] else MaterialTheme.colorScheme.outline
}

/** Round tick values that cover lo..hi in about `count` steps. */
fun niceTicks(lo: Double, hi: Double, count: Int = 3): List<Double> {
    if (!(hi > lo)) return listOf(lo)
    val raw = (hi - lo) / count
    val mag = 10.0.pow(floor(log10(raw)))
    val step = listOf(1.0, 2.0, 2.5, 5.0, 10.0).map { it * mag }.first { it >= raw }
    val first = ceil(lo / step) * step
    val out = ArrayList<Double>()
    var v = first
    while (v <= hi + step * 1e-6) {
        out.add(v)
        v += step
    }
    return out
}

private fun indexAt(x: Float, width: Float, n: Int): Int = if (n <= 1 || width <= 0f) 0 else ((x / width) * (n - 1)).roundToInt().coerceIn(0, n - 1)

@Composable
private fun rememberDrawIn(key: Any?): Float {
    val a = remember(key) { Animatable(0f) }
    LaunchedEffect(key) { a.animateTo(1f, tween(650, easing = FastOutSlowInEasing)) }
    return a.value
}

@Composable
fun LegendItem(color: Color, name: String, value: String? = null, dashed: Boolean = false, modifier: Modifier = Modifier, spread: Boolean = false) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        if (dashed) {
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) { repeat(3) { Box(Modifier.size(width = 4.dp, height = 2.dp).background(color)) } }
        } else {
            Box(Modifier.size(10.dp).clip(CircleShape).background(color))
        }
        Spacer(Modifier.width(6.dp))
        Text(name, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = spread))
        if (value != null) {
            Spacer(Modifier.width(8.dp))
            Text(value, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
        }
    }
}

@Composable
private fun DateEnds(first: String, last: String) {
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(first, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(last, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun DrawScope.grid(ticks: List<Double>, y: (Double) -> Float, color: Color, label: Color, measurer: TextMeasurer, style: TextStyle, format: (Double) -> String) {
    for (t in ticks) {
        val yy = y(t)
        if (yy < 0f || yy > size.height) continue
        drawLine(color, Offset(0f, yy), Offset(size.width, yy), strokeWidth = 1.dp.toPx())
        val text = measurer.measure(format(t), style.copy(color = label))
        if (yy - text.size.height - 2.dp.toPx() >= 0f) drawText(text, topLeft = Offset(0f, yy - text.size.height - 2.dp.toPx()))
    }
}

/**
 * Value over time for a few lines. Touch or drag to read a day: the legend shows that day's values, so nothing has to
 * be read off the axis. Lines beyond the first three should be a ranked list instead (see RankRow).
 */
@Composable
fun LineChart(dates: List<String>, lines: List<ChartLine>, modifier: Modifier = Modifier, height: Dp = 208.dp, format: (Double) -> String = Fmt::inrShort) {
    val n = dates.size
    if (n < 2 || lines.isEmpty()) return
    var scrub by remember(n) { mutableStateOf<Int?>(null) }
    val at = scrub ?: (n - 1)
    val progress = rememberDrawIn(n)
    val all = lines.flatMap { it.values }
    val lo = all.min()
    val hi = all.max()
    val pad = ((hi - lo).takeIf { it > 0 } ?: max(abs(hi), 1.0)) * 0.08
    val y0 = lo - pad
    val y1 = hi + pad
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val surface = MaterialTheme.colorScheme.surfaceContainerLow
    val measurer = rememberTextMeasurer()
    val tickStyle = MaterialTheme.typography.labelSmall
    Column(modifier) {
        Text(if (scrub == null) "Latest, ${prettyDate(dates[at])}" else prettyDate(dates[at]), style = MaterialTheme.typography.labelMedium, color = labelColor)
        Spacer(Modifier.height(6.dp))
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            for (l in lines) LegendItem(l.color, l.name, l.values.getOrNull(at)?.let(format), dashed = l.dashed, modifier = Modifier.fillMaxWidth(), spread = true)
        }
        Spacer(Modifier.height(10.dp))
        Canvas(
            Modifier.fillMaxWidth().height(height)
                .semantics { contentDescription = "Line chart of " + lines.joinToString(", ") { it.name } + ". Touch to read a day." }
                .pointerInput(n) { detectTapGestures(onPress = { scrub = indexAt(it.x, size.width.toFloat(), n) }) }
                .pointerInput(n) { detectHorizontalDragGestures(onDragEnd = { scrub = null }, onDragCancel = { scrub = null }) { change, _ -> scrub = indexAt(change.position.x, size.width.toFloat(), n) } },
        ) {
            val w = size.width
            val h = size.height
            fun x(i: Int) = w * i / (n - 1)
            fun y(v: Double) = (h - (v - y0) / (y1 - y0) * h).toFloat()
            grid(niceTicks(y0, y1), ::y, gridColor, labelColor, measurer, tickStyle, Fmt::inrCompact)
            clipRect(right = w * progress) {
                for (l in lines) {
                    val path = Path()
                    l.values.forEachIndexed { i, v -> if (i == 0) path.moveTo(x(i), y(v)) else path.lineTo(x(i), y(v)) }
                    drawPath(
                        path, l.color,
                        style = Stroke(
                            width = (if (l.dashed) 1.5.dp else 2.dp).toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round,
                            pathEffect = if (l.dashed) PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 4.dp.toPx())) else null,
                        ),
                    )
                }
            }
            if (scrub != null) drawLine(labelColor, Offset(x(at), 0f), Offset(x(at), h), strokeWidth = 1.dp.toPx())
            if (progress >= 1f || scrub != null) {
                for (l in lines) {
                    val v = l.values.getOrNull(at) ?: continue
                    if (l.dashed && scrub == null) continue
                    drawCircle(surface, radius = 6.dp.toPx(), center = Offset(x(at), y(v)))
                    drawCircle(l.color, radius = 4.dp.toPx(), center = Offset(x(at), y(v)))
                }
            }
        }
        DateEnds(prettyDate(dates.first()), prettyDate(dates.last()))
    }
}

/** Where the money sat over time: one band per sleeve, stacked from zero. Touch to read a day. */
@Composable
fun StackedAreaChart(dates: List<String>, layers: List<ChartLayer>, modifier: Modifier = Modifier, height: Dp = 188.dp) {
    val n = dates.size
    val shown = layers.filter { l -> l.values.any { it > 0 } }
    if (n < 2 || shown.isEmpty()) return
    var scrub by remember(n) { mutableStateOf<Int?>(null) }
    val at = scrub ?: (n - 1)
    val progress = rememberDrawIn(n to shown.size)
    val totals = (0 until n).map { i -> shown.sumOf { it.values.getOrElse(i) { 0.0 } } }
    val top = (totals.max().takeIf { it > 0 } ?: 1.0) * 1.06
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val surface = MaterialTheme.colorScheme.surfaceContainerLow
    val measurer = rememberTextMeasurer()
    val tickStyle = MaterialTheme.typography.labelSmall
    Column(modifier) {
        Text(if (scrub == null) "Latest, ${prettyDate(dates[at])}" else prettyDate(dates[at]), style = MaterialTheme.typography.labelMedium, color = labelColor)
        Spacer(Modifier.height(6.dp))
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            for (l in shown) {
                val v = l.values.getOrElse(at) { 0.0 }
                val share = if (totals[at] > 0) v / totals[at] else 0.0
                LegendItem(l.color, l.name, if (v < 1) "None" else "${Fmt.inrShort(v)}  ${Fmt.pct(share, 0)}", modifier = Modifier.fillMaxWidth(), spread = true)
            }
        }
        Spacer(Modifier.height(10.dp))
        Canvas(
            Modifier.fillMaxWidth().height(height)
                .semantics { contentDescription = "Stacked chart of " + shown.joinToString(", ") { it.name } + " over time. Touch to read a day." }
                .pointerInput(n) { detectTapGestures(onPress = { scrub = indexAt(it.x, size.width.toFloat(), n) }) }
                .pointerInput(n) { detectHorizontalDragGestures(onDragEnd = { scrub = null }, onDragCancel = { scrub = null }) { change, _ -> scrub = indexAt(change.position.x, size.width.toFloat(), n) } },
        ) {
            val w = size.width
            val h = size.height
            fun x(i: Int) = w * i / (n - 1)
            fun y(v: Double) = (h - v / top * h).toFloat()
            clipRect(right = w * progress) {
                val base = DoubleArray(n)
                for (l in shown) {
                    val upper = DoubleArray(n) { i -> base[i] + l.values.getOrElse(i) { 0.0 } }
                    val area = Path()
                    for (i in 0 until n) if (i == 0) area.moveTo(x(i), y(upper[i])) else area.lineTo(x(i), y(upper[i]))
                    for (i in n - 1 downTo 0) area.lineTo(x(i), y(base[i]))
                    area.close()
                    drawPath(area, l.color.copy(alpha = 0.86f))
                    // the gap between bands is drawn in the surface colour, so neighbours separate without an outline
                    val edge = Path()
                    for (i in 0 until n) if (i == 0) edge.moveTo(x(i), y(upper[i])) else edge.lineTo(x(i), y(upper[i]))
                    drawPath(edge, surface, style = Stroke(width = 2.dp.toPx(), join = StrokeJoin.Round))
                    for (i in 0 until n) base[i] = upper[i]
                }
            }
            grid(niceTicks(0.0, top).filter { it > 0 }, ::y, gridColor.copy(alpha = 0.7f), labelColor, measurer, tickStyle, Fmt::inrCompact)
            if (scrub != null) drawLine(labelColor, Offset(x(at), 0f), Offset(x(at), h), strokeWidth = 1.dp.toPx())
        }
        DateEnds(prettyDate(dates.first()), prettyDate(dates.last()))
    }
}

data class MonthFlow(val month: String, val bought: Double, val sold: Double)

/** Money moved each month: buys rise above the line, sells hang below it. Touch a month to read it. */
@Composable
fun FlowColumns(flows: List<MonthFlow>, modifier: Modifier = Modifier, height: Dp = 140.dp) {
    if (flows.isEmpty()) return
    val t = LocalTokens.current
    val n = flows.size
    var pick by remember(n) { mutableStateOf<Int?>(null) }
    val peak = flows.maxOf { max(it.bought, it.sold) }
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val progress = rememberDrawIn(n)
    Column(modifier) {
        val p = pick
        val bought = if (p == null) flows.sumOf { it.bought } else flows[p].bought
        val sold = if (p == null) flows.sumOf { it.sold } else flows[p].sold
        Text(if (p == null) "Whole period" else monthLabel(flows[p].month), style = MaterialTheme.typography.labelMedium, color = labelColor)
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            LegendItem(t.buy, "Bought", Fmt.inrShort(bought))
            LegendItem(t.sell, "Sold", Fmt.inrShort(sold))
        }
        Spacer(Modifier.height(10.dp))
        if (peak <= 0) {
            Muted("No money moved. This strategy never traded in the period.")
            return@Column
        }
        Canvas(
            Modifier.fillMaxWidth().height(height)
                .semantics { contentDescription = "Columns of money bought and sold each month. Touch a month to read it." }
                .pointerInput(n) {
                    detectTapGestures { o ->
                        val i = (o.x / size.width * n).toInt().coerceIn(0, n - 1)
                        pick = if (pick == i) null else i
                    }
                },
        ) {
            val slot = size.width / n
            val bar = min(slot - 2.dp.toPx(), 18.dp.toPx()).coerceAtLeast(2.dp.toPx())
            val mid = size.height / 2
            val scale = (mid - 4.dp.toPx()) / peak.toFloat() * progress
            val r = CornerRadius(min(4.dp.toPx(), bar / 2))
            flows.forEachIndexed { i, f ->
                val left = slot * i + (slot - bar) / 2
                val dim = pick != null && pick != i
                if (f.bought > 0) {
                    val hgt = max((f.bought * scale).toFloat(), 2.dp.toPx())
                    drawDataBar(t.buy.copy(alpha = if (dim) 0.35f else 1f), Rect(left, mid - 1.dp.toPx() - hgt, left + bar, mid - 1.dp.toPx()), r, up = true)
                }
                if (f.sold > 0) {
                    val hgt = max((f.sold * scale).toFloat(), 2.dp.toPx())
                    drawDataBar(t.sell.copy(alpha = if (dim) 0.35f else 1f), Rect(left, mid + 1.dp.toPx(), left + bar, mid + 1.dp.toPx() + hgt), r, up = false)
                }
            }
            drawLine(gridColor, Offset(0f, mid), Offset(size.width, mid), strokeWidth = 1.dp.toPx())
        }
        DateEnds(monthLabel(flows.first().month), monthLabel(flows.last().month))
    }
}

/** A bar that is square on the baseline and rounded at the data end. */
private fun DrawScope.drawDataBar(color: Color, rect: Rect, r: CornerRadius, up: Boolean) {
    val path = Path().apply {
        addRoundRect(
            androidx.compose.ui.geometry.RoundRect(
                rect,
                topLeft = if (up) r else CornerRadius.Zero, topRight = if (up) r else CornerRadius.Zero,
                bottomLeft = if (up) CornerRadius.Zero else r, bottomRight = if (up) CornerRadius.Zero else r,
            ),
        )
    }
    drawPath(path, color)
}

private val MONTHS = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

/** "2025-03" -> "Mar 2025" */
fun monthLabel(ym: String): String {
    val m = ym.substringAfter('-', "").toIntOrNull() ?: return ym
    return if (m in 1..12) "${MONTHS[m - 1]} ${ym.substringBefore('-')}" else ym
}

/** One strategy in a ranked list: a thin bar from zero, with a tick where the money put in sits. */
@Composable
fun RankBar(value: Double, max: Double, marker: Double, color: Color, modifier: Modifier = Modifier) {
    val track = MaterialTheme.colorScheme.surfaceContainerHighest
    val tick = MaterialTheme.colorScheme.onSurface
    Canvas(modifier.fillMaxWidth().height(14.dp)) {
        val h = 8.dp.toPx()
        val top = (size.height - h) / 2
        val r = CornerRadius(h / 2)
        drawRoundRect(track, Offset(0f, top), Size(size.width, h), r)
        if (max > 0 && value > 0) drawRoundRect(color, Offset(0f, top), Size((size.width * (value / max)).toFloat().coerceIn(h, size.width), h), r)
        if (max > 0 && marker > 0) {
            val x = (size.width * (marker / max)).toFloat().coerceIn(1f, size.width - 1f)
            drawLine(tick, Offset(x, 0f), Offset(x, size.height), strokeWidth = 2.dp.toPx())
        }
    }
}

data class FlowNode(val label: String, val value: Double)

/**
 * The plan as moving money: what is sold on the left, what is bought on the right, and a ribbon for each rupee's path.
 * Proceeds are shared across the buys in proportion to their size (the engine funds buys from the pooled sales).
 * Pass both sides with the same total: the caller adds a cash node to the smaller side.
 */
@Composable
fun MoneyFlow(sells: List<FlowNode>, buys: List<FlowNode>, modifier: Modifier = Modifier) {
    val left = sells.filter { it.value > 0 }
    val right = buys.filter { it.value > 0 }
    if (left.isEmpty() || right.isEmpty()) return
    val t = LocalTokens.current
    val ribbon = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.16f)
    val cashColor = MaterialTheme.colorScheme.outline     // cash is where money rests, not a sale or a purchase
    val ink = MaterialTheme.colorScheme.onSurface
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val measurer = rememberTextMeasurer()
    val nameStyle = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.SemiBold)
    val valueStyle = MaterialTheme.typography.labelMedium
    val rows = max(left.size, right.size)
    val progress = rememberDrawIn(left.size to right.size)
    Column(modifier) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Sell", style = MaterialTheme.typography.labelMedium, color = muted)
            Text("Buy", style = MaterialTheme.typography.labelMedium, color = muted)
        }
        Spacer(Modifier.height(6.dp))
        Canvas(
            Modifier.fillMaxWidth().height((rows * 52).coerceAtLeast(120).dp).semantics {
                contentDescription = "Money flow. Sell " + left.joinToString(", ") { "${it.label} ${Fmt.inrShort(it.value)}" } + ". Buy " + right.joinToString(", ") { "${it.label} ${Fmt.inrShort(it.value)}" } + "."
            },
        ) {
            val bar = 8.dp.toPx()
            val gap = 10.dp.toPx()
            val total = max(left.sumOf { it.value }, right.sumOf { it.value })
            fun layout(nodes: List<FlowNode>): List<Pair<Float, Float>> {
                val usable = size.height - gap * (nodes.size - 1)
                val scale = usable / total.toFloat()
                var y = (size.height - (nodes.sumOf { it.value }.toFloat() * scale + gap * (nodes.size - 1))) / 2
                return nodes.map { nd ->
                    val hgt = max((nd.value * scale).toFloat(), 3.dp.toPx())
                    (y to hgt).also { y += hgt + gap }
                }
            }
            val l = layout(left)
            val r = layout(right)
            val sumL = left.sumOf { it.value }
            val sumR = right.sumOf { it.value }
            val x0 = bar
            val x1 = size.width - bar
            val usedL = FloatArray(left.size)
            val usedR = FloatArray(right.size)
            clipRect(right = x0 + (x1 - x0) * progress) {
                left.forEachIndexed { i, s ->
                    right.forEachIndexed { j, b ->
                        // each sale is split across the buys by their size, and each buy is filled by the sales by theirs
                        val hl = (l[i].second * (b.value / sumR)).toFloat()
                        val hr = (r[j].second * (s.value / sumL)).toFloat()
                        if (hl > 0.5f && hr > 0.5f) {
                            val yl = l[i].first + usedL[i]
                            val yr = r[j].first + usedR[j]
                            val mid = (x0 + x1) / 2
                            val p = Path().apply {
                                moveTo(x0, yl)
                                cubicTo(mid, yl, mid, yr, x1, yr)
                                lineTo(x1, yr + hr)
                                cubicTo(mid, yr + hr, mid, yl + hl, x0, yl + hl)
                                close()
                            }
                            drawPath(p, ribbon)
                        }
                        usedL[i] += hl
                        usedR[j] += hr
                    }
                }
            }
            val corner = CornerRadius(3.dp.toPx())
            left.forEachIndexed { i, s ->
                drawRoundRect(if (s.label == "Cash") cashColor else t.sell, Offset(0f, l[i].first), Size(bar, l[i].second), corner)
                val name = measurer.measure(s.label, nameStyle.copy(color = ink), maxLines = 1)
                val value = measurer.measure(Fmt.inrShort(s.value), valueStyle.copy(color = muted), maxLines = 1)
                val top = (l[i].first + l[i].second / 2 - (name.size.height + value.size.height) / 2).coerceIn(0f, size.height - name.size.height - value.size.height)
                drawText(name, topLeft = Offset(bar + 8.dp.toPx(), top))
                drawText(value, topLeft = Offset(bar + 8.dp.toPx(), top + name.size.height))
            }
            right.forEachIndexed { j, b ->
                drawRoundRect(if (b.label == "Cash") cashColor else t.buy, Offset(size.width - bar, r[j].first), Size(bar, r[j].second), corner)
                val name = measurer.measure(b.label, nameStyle.copy(color = ink), maxLines = 1)
                val value = measurer.measure(Fmt.inrShort(b.value), valueStyle.copy(color = muted), maxLines = 1)
                val top = (r[j].first + r[j].second / 2 - (name.size.height + value.size.height) / 2).coerceIn(0f, size.height - name.size.height - value.size.height)
                drawText(name, topLeft = Offset(size.width - bar - 8.dp.toPx() - name.size.width, top))
                drawText(value, topLeft = Offset(size.width - bar - 8.dp.toPx() - value.size.width, top + name.size.height))
            }
        }
    }
}

/**
 * The closes of one waiting window. Days before the window opened are faint, the watching phase is shaded, and the
 * day the rule trades carries a ring. `better` says which direction is good: lower for a buy, higher for a sell.
 */
@Composable
fun WindowChart(prices: List<Double>, opened: Int, cutoff: Int, fired: Int?, modifier: Modifier = Modifier, height: Dp = 120.dp) {
    val n = prices.size
    if (n < 2) return
    val t = LocalTokens.current
    val line = t.series[0]
    val faint = MaterialTheme.colorScheme.outline
    val band = MaterialTheme.colorScheme.surfaceContainerHighest
    val surface = MaterialTheme.colorScheme.surfaceContainerLow
    val ink = MaterialTheme.colorScheme.onSurface
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val measurer = rememberTextMeasurer()
    val style = MaterialTheme.typography.labelSmall
    val lo = prices.min()
    val hi = prices.max()
    val pad = ((hi - lo).takeIf { it > 0 } ?: 1.0) * 0.18
    Canvas(modifier.fillMaxWidth().height(height).semantics { contentDescription = "Closing prices over the last $n trading days" }) {
        val inset = 8.dp.toPx()
        val w = size.width - inset * 2
        val h = size.height - 18.dp.toPx()
        fun x(i: Int) = inset + w * i / (n - 1)
        fun y(v: Double) = (h - (v - (lo - pad)) / (hi - lo + 2 * pad) * h).toFloat()
        val watchEnd = min(opened + cutoff - 1, n - 1)
        if (cutoff > 0 && opened <= n - 1) {
            val half = w / (n - 1) / 2
            drawRoundRect(band, Offset(x(opened) - half.coerceAtMost(inset), 0f), Size(x(watchEnd) - x(opened) + half.coerceAtMost(inset) + half, h), CornerRadius(6.dp.toPx()))
            val label = measurer.measure("Watching", style.copy(color = muted))
            if (label.size.width < x(watchEnd) - x(opened) + half * 2) drawText(label, topLeft = Offset(x(opened), h + 3.dp.toPx()))
        }
        if (opened > 0) {
            val before = Path()
            for (i in 0..opened) if (i == 0) before.moveTo(x(i), y(prices[i])) else before.lineTo(x(i), y(prices[i]))
            drawPath(before, faint, style = Stroke(1.5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round, pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 4.dp.toPx()))))
        }
        val path = Path()
        for (i in opened until n) if (i == opened) path.moveTo(x(i), y(prices[i])) else path.lineTo(x(i), y(prices[i]))
        drawPath(path, line, style = Stroke(2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        for (i in opened until n) {
            drawCircle(surface, 4.5.dp.toPx(), Offset(x(i), y(prices[i])))
            drawCircle(line, 2.5.dp.toPx(), Offset(x(i), y(prices[i])))
        }
        if (fired != null && fired in 0 until n) {
            val c = Offset(x(fired), y(prices[fired]))
            drawCircle(surface, 9.dp.toPx(), c)
            drawCircle(ink, 7.dp.toPx(), c, style = Stroke(2.dp.toPx()))
            drawCircle(line, 4.dp.toPx(), c)
        }
        val today = measurer.measure("Today", style.copy(color = muted))
        drawText(today, topLeft = Offset(size.width - today.size.width, h + 3.dp.toPx()))
    }
}

/** A row of swatch and label pairs for charts whose legend is not also a readout. */
@Composable
fun LegendRow(items: List<Pair<Color, String>>, modifier: Modifier = Modifier) {
    FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for ((c, name) in items) LegendItem(c, name)
    }
}

/** A stat with a large value, for the one number a screen leads with. */
@Composable
fun HeroNumber(label: String, value: String, modifier: Modifier = Modifier, note: String? = null, noteColor: Color = MaterialTheme.colorScheme.onSurfaceVariant) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (note != null) Text(note, style = MaterialTheme.typography.bodyMedium, color = noteColor)
    }
}

/** Small rounded tag used to mark a row, for example "Your setting". */
@Composable
fun Tag(text: String, modifier: Modifier = Modifier) {
    Text(
        text, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSecondaryContainer,
        modifier = modifier.clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}
