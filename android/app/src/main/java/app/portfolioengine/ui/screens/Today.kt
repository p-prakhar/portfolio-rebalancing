package app.portfolioengine.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.portfolioengine.MainViewModel
import app.portfolioengine.UiState
import app.portfolioengine.model.Fmt
import app.portfolioengine.model.bool
import app.portfolioengine.model.int
import app.portfolioengine.model.num
import app.portfolioengine.model.obj
import app.portfolioengine.model.objects
import app.portfolioengine.model.str
import app.portfolioengine.model.strings
import app.portfolioengine.ui.Routes
import app.portfolioengine.ui.components.AppButton
import app.portfolioengine.ui.components.AllocationBar
import app.portfolioengine.ui.components.AppCard
import app.portfolioengine.ui.components.Bullets
import app.portfolioengine.ui.components.BusyLine
import app.portfolioengine.ui.components.Disclosure
import app.portfolioengine.ui.components.EmptyState
import app.portfolioengine.ui.components.HeroNumber
import app.portfolioengine.ui.components.LevelDot
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.components.Pill
import app.portfolioengine.ui.components.SectionTitle
import app.portfolioengine.ui.components.Stat
import app.portfolioengine.ui.components.prettyDate
import app.portfolioengine.ui.components.sleeveLabel
import app.portfolioengine.ui.theme.LocalTokens
import org.json.JSONObject

/** Tab 1 answers one question: should I rebalance today? */
@Composable
fun TodayTab(vm: MainViewModel, state: UiState, openPlan: () -> Unit, go: (String) -> Unit) {
    val d = state.check
    PullToRefreshBox(isRefreshing = state.checking, onRefresh = { vm.runCheck(refresh = true) }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Should I rebalance?", style = MaterialTheme.typography.headlineSmall)
                    if (d != null) Muted("Prices to ${prettyDate(d.str("asof"))}")
                }
                IconButton(onClick = { vm.runCheck(refresh = true) }, enabled = !state.checking) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Check again with fresh prices")
                }
            }
            BusyLine(state.checking)
            Spacer(Modifier.height(8.dp))

            if (state.checkError != null) {
                AppCard {
                    Text(if (d == null) "Could not run the check" else "Could not refresh", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Muted(state.checkError)
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(onClick = { vm.runCheck(refresh = true) }) { Text("Try again") }
                }
                Spacer(Modifier.height(12.dp))
            }

            if (d == null) {
                if (state.checkError == null) EmptyState("Running your first check", "Fetching prices and working out the plan. This can take a minute the first time.")
                return@Column
            }

            HeroNumber("Your portfolio", Fmt.inrShort(d.num("nav")), Modifier.padding(top = 4.dp, bottom = 16.dp))
            Verdict(d, openPlan)

            val warnings = d.strings("warnings")
            if (warnings.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                AppCard {
                    Text("Check these", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    Bullets(warnings)
                }
            }

            if (!state.hasProfile) {
                Spacer(Modifier.height(12.dp))
                AppCard(onClick = { go(Routes.PROFILE) }) {
                    Text("Make the tax numbers exact", style = MaterialTheme.typography.titleMedium)
                    Muted("Add your age, risk appetite and income. Until then the engine assumes the top 30% slab. Takes a minute.")
                }
            }

            SectionTitle("Where the money is")
            AppCard {
                val current = bySleeve(d.objects("current"))
                val target = bySleeve(d.objects("target"))
                Muted("Now")
                Spacer(Modifier.height(6.dp))
                AllocationBar(current)
                if (target.isNotEmpty() && target != current) {
                    Spacer(Modifier.height(16.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Spacer(Modifier.height(12.dp))
                    Muted("What the model would hold")
                    Spacer(Modifier.height(6.dp))
                    // same order as "Now" so a colour means the same thing in both bars
                    AllocationBar(current.map { (k, _) -> k to (target.firstOrNull { it.first == k }?.second ?: 0.0) } + target.filter { t -> current.none { it.first == t.first } })
                }
            }

            Spacer(Modifier.height(12.dp))
            AppCard(onClick = { go(Routes.BACKTEST) }) {
                Text("See it on your own history", style = MaterialTheme.typography.titleMedium)
                Muted("How each strategy would have done with your money since the day you bought, after fees and tax.")
            }

            val guards = d.objects("guardrails")
            if (guards.isNotEmpty()) {
                SectionTitle("Guardrails")
                AppCard {
                    guards.forEachIndexed { i, g ->
                        if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Disclosure(g.str("title"), leading = { LevelDot(g.str("level")) }) { Muted(g.str("detail")) }
                    }
                }
            }

            SectionTitle("What the engine looked at")
            AppCard {
                d.objects("factors").forEachIndexed { i, f ->
                    if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Disclosure(f.str("name"), subtitle = f.str("line"), leading = { LevelDot(f.str("status")) }) { Muted(f.str("detail")) }
                }
                val why = d.strings("policy_why")
                if (why.isNotEmpty()) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Disclosure("How the strategy read the market") { Bullets(why) }
                }
                val crash = d.obj("crash").obj("assess")
                if (crash != null) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Disclosure(
                        "Crash guard", subtitle = "Level ${crash.int("level")}: ${crash.str("label")}" + if (d.obj("crash").bool("enabled")) "" else " (warnings only)",
                        leading = { LevelDot(if (crash.int("level") >= 2) "warn" else "ok") },
                    ) {
                        Bullets(crash.objects("families").map { (if (it.num("points") > 0) "On: " else "Off: ") + it.str("name") + ". " + it.str("detail") })
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            Muted(d.str("tax_note"))
            Spacer(Modifier.height(8.dp))
            Muted(d.str("data_note") + ". Decision support only: the app never places orders. Check tax with a CA before acting.")
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun Verdict(d: JSONObject, openPlan: () -> Unit) {
    val v = d.obj("verdict")
    val t = LocalTokens.current
    val rebalance = v.str("call") == "REBALANCE"
    AppCard {
        if (rebalance) Pill("REBALANCE", MaterialTheme.colorScheme.onPrimary, MaterialTheme.colorScheme.primary)
        else Pill("HOLD", MaterialTheme.colorScheme.onSecondaryContainer, MaterialTheme.colorScheme.secondaryContainer)
        Spacer(Modifier.height(10.dp))
        Text(v.str("headline"), style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(10.dp))
        Bullets(v.strings("reasons"))
        Spacer(Modifier.height(16.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Stat("Fees if you act", Fmt.inr(v.num("cost")), Modifier.weight(1f))
            Stat("Tax if you act", Fmt.inr(v.num("tax")), Modifier.weight(1f))
        }
        val n = v.int("n_trades")
        if (n > 0) {
            Spacer(Modifier.height(16.dp))
            if (rebalance) {
                AppButton(onClick = openPlan, modifier = Modifier.fillMaxWidth()) { Text("See the $n step${if (n == 1) "" else "s"}") }
            } else {
                OutlinedButton(onClick = openPlan, modifier = Modifier.fillMaxWidth()) { Text("See what was considered") }
            }
        }
        if (d.bool("demo")) {
            Spacer(Modifier.height(10.dp))
            Pill("Made-up prices", t.warn, t.warnContainer)
        }
    }
}

private fun bySleeve(nodes: List<JSONObject>): List<Pair<String, Double>> =
    nodes.groupBy { sleeveLabel(it.str("sleeve", "other")) }.map { (k, v) -> k to v.sumOf { it.num("value") } }.sortedByDescending { it.second }
