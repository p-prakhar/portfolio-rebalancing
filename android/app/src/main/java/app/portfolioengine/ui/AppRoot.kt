package app.portfolioengine.ui

import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.FactCheck
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.PieChart
import androidx.compose.material.icons.filled.Today
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.Surface
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.portfolioengine.MainViewModel
import app.portfolioengine.ui.components.Muted
import app.portfolioengine.ui.screens.AddHoldingScreen
import app.portfolioengine.ui.screens.DepositsScreen
import app.portfolioengine.ui.screens.ImportScreen
import app.portfolioengine.ui.screens.MoreTab
import app.portfolioengine.ui.screens.OnboardingScreen
import app.portfolioengine.ui.screens.OtherAssetsScreen
import app.portfolioengine.ui.screens.PlanTab
import app.portfolioengine.ui.screens.PortfolioTab
import app.portfolioengine.ui.screens.ProfileScreen
import app.portfolioengine.ui.screens.ReportsScreen
import app.portfolioengine.ui.screens.SettingsScreen
import app.portfolioengine.ui.screens.StarterScreen
import app.portfolioengine.ui.screens.TodayTab
import app.portfolioengine.ui.screens.WebScreen

object Routes {
    const val HOME = "home"
    const val IMPORT = "import"
    const val IMPORT_TYPED = "import?typed=true"
    const val STARTER = "starter"
    const val ADD = "add"
    const val ADD_FUND = "add?fund=true"
    const val PROFILE = "profile"
    const val DEPOSITS = "deposits"
    const val OTHERS = "others"
    const val REPORTS = "reports"
    const val SETTINGS = "settings"
    fun web(path: String, title: String, scripts: Boolean) = "web?path=${Uri.encode(path)}&title=${Uri.encode(title)}&scripts=$scripts"
}

@Composable
fun AppRoot(vm: MainViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()
    val incoming by vm.incoming.collectAsStateWithLifecycle()
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    // a shared file opens the import screen as soon as the engine is up
    LaunchedEffect(incoming, state.booting) {
        if (incoming.isNotEmpty() && !state.booting && state.bootError == null) {
            vm.importFiles(incoming)
            vm.incoming.value = emptyList()
            nav.navigate(Routes.IMPORT) { launchSingleTop = true }
        }
    }

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background, contentColor = MaterialTheme.colorScheme.onBackground) {
      Box(Modifier.fillMaxSize()) {
        when {
            state.booting -> Booting()
            state.bootError != null -> BootFailed(state.bootError!!, vm::boot)
            else -> AppNav(vm, nav)
        }
        // screens draw their own bars; messages float above whatever is showing
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 88.dp))
      }
    }
}

@Composable
private fun Booting() {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        Spacer(Modifier.height(20.dp))
        Text("Starting the engine", style = MaterialTheme.typography.titleMedium)
        Muted("The first start takes a few seconds.")
    }
}

@Composable
private fun BootFailed(message: String, retry: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text("The engine did not start", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(8.dp))
        Muted(message)
        Spacer(Modifier.height(20.dp))
        Button(onClick = retry) { Text("Try again") }
    }
}

@Composable
private fun AppNav(vm: MainViewModel, nav: NavHostController) {
    val back: () -> Unit = { nav.popBackStack() }
    NavHost(navController = nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) { Home(vm, nav) }
        composable("import?typed={typed}", arguments = listOf(navArgument("typed") { type = NavType.BoolType; defaultValue = false })) {
            ImportScreen(vm, typed = it.arguments?.getBoolean("typed") ?: false, onBack = back)
        }
        composable(Routes.STARTER) { StarterScreen(vm, onBack = back) }
        composable("add?fund={fund}", arguments = listOf(navArgument("fund") { type = NavType.BoolType; defaultValue = false })) {
            AddHoldingScreen(vm, fund = it.arguments?.getBoolean("fund") ?: false, onBack = back)
        }
        composable(Routes.PROFILE) { ProfileScreen(vm, onBack = back) }
        composable(Routes.DEPOSITS) { DepositsScreen(vm, onBack = back) }
        composable(Routes.OTHERS) { OtherAssetsScreen(vm, onBack = back) }
        composable(Routes.REPORTS) { ReportsScreen(vm, onBack = back, open = { p, t, s -> nav.navigate(Routes.web(p, t, s)) }) }
        composable(Routes.SETTINGS) { SettingsScreen(vm, onBack = back) }
        composable(
            "web?path={path}&title={title}&scripts={scripts}",
            arguments = listOf(
                navArgument("path") { type = NavType.StringType },
                navArgument("title") { type = NavType.StringType; defaultValue = "Report" },
                navArgument("scripts") { type = NavType.BoolType; defaultValue = false },
            ),
        ) {
            WebScreen(path = it.arguments?.getString("path").orEmpty(), title = it.arguments?.getString("title").orEmpty(), scripts = it.arguments?.getBoolean("scripts") ?: false, onBack = back)
        }
    }
}

private data class Tab(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

@Composable
private fun Home(vm: MainViewModel, nav: NavHostController) {
    val state by vm.state.collectAsStateWithLifecycle()
    val go: (String) -> Unit = { nav.navigate(it) { launchSingleTop = true } }
    if (!state.hasHoldings) {
        OnboardingScreen(vm, go)
        return
    }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val tabs = remember {
        listOf(Tab("Today", Icons.Filled.Today), Tab("Plan", Icons.AutoMirrored.Filled.FactCheck), Tab("Portfolio", Icons.Filled.PieChart), Tab("More", Icons.Filled.Menu))
    }
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        contentColor = MaterialTheme.colorScheme.onBackground,
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainer) {
                tabs.forEachIndexed { i, t ->
                    NavigationBarItem(selected = tab == i, onClick = { tab = i }, icon = { Icon(t.icon, contentDescription = null) }, label = { Text(t.label) })
                }
            }
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            when (tab) {
                0 -> TodayTab(vm, state, openPlan = { tab = 1 }, go = go)
                1 -> PlanTab(vm, state)
                2 -> PortfolioTab(vm, state, go)
                else -> MoreTab(vm, state, go)
            }
        }
    }
}
