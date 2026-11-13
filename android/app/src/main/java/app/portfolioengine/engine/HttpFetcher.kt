package app.portfolioengine.engine

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * HTTP transport handed to the Python price client (pe/yahoo_lite.py: set_fetcher), so requests use the
 * platform's own network stack. It says plainly what it is and does not retry around refusals.
 */
class HttpFetcher {
    fun get(url: String): String {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.connectTimeout = 15_000
            c.readTimeout = 25_000
            c.instanceFollowRedirects = true
            c.setRequestProperty("User-Agent", "portfolio-engine-android/1.0 (personal portfolio tracker)")
            c.setRequestProperty("Accept", "application/json")
            val code = c.responseCode
            if (code !in 200..299) throw IOException("HTTP $code")
            return c.inputStream.bufferedReader().use { it.readText() }
        } finally {
            c.disconnect()
        }
    }
}
