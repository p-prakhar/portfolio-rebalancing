package app.portfolioengine.model

import org.json.JSONArray
import org.json.JSONObject

/** Small helpers so the screens can read the engine's JSON without null checks everywhere. */
fun JSONObject?.str(key: String, default: String = ""): String =
    if (this == null || isNull(key)) default else optString(key, default)

fun JSONObject?.num(key: String, default: Double = 0.0): Double =
    if (this == null || isNull(key)) default else optDouble(key, default).let { if (it.isNaN()) default else it }

fun JSONObject?.numOrNull(key: String): Double? =
    if (this == null || isNull(key) || !has(key)) null else optDouble(key).takeUnless { it.isNaN() }

fun JSONObject?.int(key: String, default: Int = 0): Int = if (this == null || isNull(key)) default else optInt(key, default)

fun JSONObject?.bool(key: String, default: Boolean = false): Boolean =
    if (this == null || isNull(key)) default else optBoolean(key, default)

fun JSONObject?.obj(key: String): JSONObject? = if (this == null || isNull(key)) null else optJSONObject(key)

fun JSONObject?.objects(key: String): List<JSONObject> = (if (this == null || isNull(key)) null else optJSONArray(key)).objects()

fun JSONObject?.strings(key: String): List<String> = (if (this == null || isNull(key)) null else optJSONArray(key)).strings()

fun JSONArray?.objects(): List<JSONObject> {
    if (this == null) return emptyList()
    val out = ArrayList<JSONObject>(length())
    for (i in 0 until length()) optJSONObject(i)?.let { out.add(it) }
    return out
}

fun JSONArray?.strings(): List<String> {
    if (this == null) return emptyList()
    val out = ArrayList<String>(length())
    for (i in 0 until length()) if (!isNull(i)) out.add(optString(i))
    return out
}

fun jsonOf(vararg pairs: Pair<String, Any?>): String {
    val o = JSONObject()
    for ((k, v) in pairs) {
        when (v) {
            null -> {}
            is List<*> -> o.put(k, JSONArray(v))
            is Map<*, *> -> o.put(k, JSONObject(v))
            else -> o.put(k, v)
        }
    }
    return o.toString()
}
