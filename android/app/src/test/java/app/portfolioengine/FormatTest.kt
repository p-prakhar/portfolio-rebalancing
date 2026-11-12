package app.portfolioengine

import app.portfolioengine.engine.Engine
import app.portfolioengine.engine.EngineResult
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.jsonOf
import app.portfolioengine.model.num
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FormatTest {
    @Test
    fun groupsDigitsTheIndianWay() {
        assertEquals("0", Fmt.grouped(0))
        assertEquals("999", Fmt.grouped(999))
        assertEquals("1,000", Fmt.grouped(1000))
        assertEquals("12,34,567", Fmt.grouped(1234567))
        assertEquals("-1,00,000", Fmt.grouped(-100000))
        assertEquals("₹12,34,567", Fmt.inr(1234567.4))
    }

    @Test
    fun shortensToLakhAndCrore() {
        assertEquals("₹45,000", Fmt.inrShort(45000.0))
        assertEquals("₹1.5 lakh", Fmt.inrShort(150000.0))
        assertEquals("₹16.2 lakh", Fmt.inrShort(1620000.0))
        assertEquals("₹1.25 crore", Fmt.inrShort(12500000.0))
        assertEquals("-₹2 lakh", Fmt.inrShort(-200000.0))
    }

    @Test
    fun parsesAmountsPeopleType() {
        assertEquals(500000.0, Fmt.parseAmount("5 lakh")!!, 0.001)
        assertEquals(25000000.0, Fmt.parseAmount("2.5cr")!!, 0.001)
        assertEquals(45000.0, Fmt.parseAmount("45k")!!, 0.001)
        assertEquals(1234567.0, Fmt.parseAmount("₹12,34,567")!!, 0.001)
        assertNull(Fmt.parseAmount("about five"))
        assertNull(Fmt.parseAmount(""))
    }

    @Test
    fun decodesTheEngineEnvelope() {
        val ok = Engine.decode("""{"ok": true, "data": {"nav": 1000.5, "trades": [{"symbol": "NIFTYBEES"}], "note": null}}""")
        assertTrue(ok is EngineResult.Ok)
        val d = (ok as EngineResult.Ok).obj
        assertEquals(1000.5, d.num("nav"), 0.0)
        assertEquals("NIFTYBEES", d.objects("trades").first().str("symbol"))
        assertEquals("", d.str("note"))
        val err = Engine.decode("""{"ok": false, "kind": "no_holdings", "error": "Add your holdings first."}""")
        assertEquals(EngineResult.Err("no_holdings", "Add your holdings first."), err)
    }

    @Test
    fun buildsPayloadsWithoutNulls() {
        val o = JSONObject(jsonOf("symbol" to "TCS", "qty" to 3, "price" to null, "paths" to listOf("a", "b")))
        assertEquals("TCS", o.getString("symbol"))
        assertTrue(!o.has("price"))
        assertEquals(2, o.getJSONArray("paths").length())
    }

    @Test
    fun compactAxisLabels() {
        assertEquals("₹50K", Fmt.inrCompact(50000.0))
        assertEquals("₹8.5L", Fmt.inrCompact(850000.0))
        assertEquals("₹10L", Fmt.inrCompact(1000000.0))
        assertEquals("₹1.25Cr", Fmt.inrCompact(12500000.0))
        assertEquals("₹900", Fmt.inrCompact(900.0))
        assertEquals("+12.5%", Fmt.signedPct(0.125))
        assertEquals("-₹1.5 lakh", Fmt.signedInrShort(-150000.0))
    }
}
