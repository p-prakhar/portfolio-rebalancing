package app.portfolioengine.model

import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToLong

/** Rupee and number formatting the Indian way: 12,34,567 and lakh / crore for big figures. */
object Fmt {
    /** 1234567 -> "12,34,567" */
    fun grouped(n: Long): String {
        val neg = n < 0
        val s = abs(n).toString()
        if (s.length <= 3) return (if (neg) "-" else "") + s
        val head = s.dropLast(3)
        val tail = s.takeLast(3)
        val parts = ArrayList<String>()
        var h = head
        while (h.length > 2) {
            parts.add(0, h.takeLast(2))
            h = h.dropLast(2)
        }
        if (h.isNotEmpty()) parts.add(0, h)
        return (if (neg) "-" else "") + parts.joinToString(",") + "," + tail
    }

    /** Exact rupees: "₹12,34,567". */
    fun inr(v: Double): String = (if (v < 0) "-" else "") + "₹" + grouped(abs(v).roundToLong())

    /** Short rupees for headlines: "₹12.3 lakh", "₹1.25 crore", "₹45,000". */
    fun inrShort(v: Double): String {
        val a = abs(v)
        val sign = if (v < 0) "-" else ""
        return when {
            a >= 1e7 -> sign + "₹" + trim(a / 1e7, 2) + " crore"
            a >= 1e5 -> sign + "₹" + trim(a / 1e5, if (a >= 1e6) 1 else 2) + " lakh"
            else -> sign + "₹" + grouped(a.roundToLong())
        }
    }

    fun signedInr(v: Double): String = (if (v > 0) "+" else "") + inr(v)

    fun pct(fraction: Double, digits: Int = 1): String = String.format(Locale.US, "%.${digits}f%%", fraction * 100)

    fun qty(v: Double): String = if (abs(v - v.roundToLong()) < 1e-6) grouped(v.roundToLong()) else trim(v, 3)

    fun price(v: Double): String = String.format(Locale.US, "%,.2f", v)

    private fun trim(v: Double, digits: Int): String =
        String.format(Locale.US, "%.${digits}f", v).trimEnd('0').trimEnd('.')

    /** "5 lakh", "2.5cr", "45,000", "45k" typed into an amount field -> rupees. Null if it is not a number. */
    fun parseAmount(text: String): Double? {
        val t = text.trim().lowercase(Locale.US).replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "").trim()
        if (t.isEmpty()) return null
        val m = Regex("""^(-?\d*\.?\d+)\s*(k|l|lakh|lakhs|lac|cr|crore|crores)?$""").find(t) ?: return null
        val base = m.groupValues[1].toDoubleOrNull() ?: return null
        val mult = when (m.groupValues[2]) {
            "k" -> 1e3
            "l", "lakh", "lakhs", "lac" -> 1e5
            "cr", "crore", "crores" -> 1e7
            else -> 1.0
        }
        return base * mult
    }
}
