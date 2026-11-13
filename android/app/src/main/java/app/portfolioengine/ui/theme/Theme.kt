package app.portfolioengine.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Tokens. Warm neutrals with one deep green accent. BUY and SELL keep their own green and red everywhere.
// The categorical series colours are used in this fixed order, never cycled. The order is checked for colour-blind and
// normal-vision separation between neighbours on both surfaces; each sleeve owns one slot (see sleeveSlot in Charts.kt).
private val Light = lightColorScheme(
    primary = Color(0xFF1F5A4C), onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDCEBE5), onPrimaryContainer = Color(0xFF0E3229),
    secondary = Color(0xFF5E5B52), onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFEFECE3), onSecondaryContainer = Color(0xFF2B2A26),
    tertiary = Color(0xFF8A6A1F), onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFF6EBCB), onTertiaryContainer = Color(0xFF3F2F08),
    background = Color(0xFFFBFAF7), onBackground = Color(0xFF1D1D1B),
    surface = Color(0xFFFBFAF7), onSurface = Color(0xFF1D1D1B),
    surfaceVariant = Color(0xFFF0EEE7), onSurfaceVariant = Color(0xFF5F5E59),
    surfaceContainerLowest = Color(0xFFFFFFFF), surfaceContainerLow = Color(0xFFFFFFFF),
    surfaceContainer = Color(0xFFF5F3EE), surfaceContainerHigh = Color(0xFFEFEDE6), surfaceContainerHighest = Color(0xFFE9E6DE),
    outline = Color(0xFFB9B6AC), outlineVariant = Color(0xFFE3E1DA),
    error = Color(0xFFB3261E), onError = Color(0xFFFFFFFF), errorContainer = Color(0xFFF9DEDC), onErrorContainer = Color(0xFF5C1512),
)

private val Dark = darkColorScheme(
    primary = Color(0xFF8FCDBB), onPrimary = Color(0xFF07382D),
    primaryContainer = Color(0xFF1F4A3F), onPrimaryContainer = Color(0xFFCDEBE1),
    secondary = Color(0xFFC9C6BC), onSecondary = Color(0xFF2B2A26),
    secondaryContainer = Color(0xFF33322E), onSecondaryContainer = Color(0xFFE6E3DA),
    tertiary = Color(0xFFE3C16F), onTertiary = Color(0xFF3F2F08),
    tertiaryContainer = Color(0xFF4A3A12), onTertiaryContainer = Color(0xFFF6EBCB),
    background = Color(0xFF141413), onBackground = Color(0xFFECEBE6),
    surface = Color(0xFF141413), onSurface = Color(0xFFECEBE6),
    surfaceVariant = Color(0xFF2A2927), onSurfaceVariant = Color(0xFFB0AEA7),
    surfaceContainerLowest = Color(0xFF0F0F0E), surfaceContainerLow = Color(0xFF1D1D1B),
    surfaceContainer = Color(0xFF1D1D1B), surfaceContainerHigh = Color(0xFF272725), surfaceContainerHighest = Color(0xFF31302E),
    outline = Color(0xFF6E6C66), outlineVariant = Color(0xFF33322F),
    error = Color(0xFFF2B8B5), onError = Color(0xFF601410), errorContainer = Color(0xFF8C1D18), onErrorContainer = Color(0xFFF9DEDC),
)

@Immutable
data class Tokens(
    val buy: Color, val buyContainer: Color,
    val sell: Color, val sellContainer: Color,
    val warn: Color, val warnContainer: Color,
    val series: List<Color>,
)

private val LightTokens = Tokens(
    buy = Color(0xFF1B7F4B), buyContainer = Color(0xFFDDF1E5),
    sell = Color(0xFFB83A2E), sellContainer = Color(0xFFF8E0DC),
    warn = Color(0xFF8A6A1F), warnContainer = Color(0xFFF6EBCB),
    series = listOf(Color(0xFF2A78D6), Color(0xFFEB6834), Color(0xFF1BAF7A), Color(0xFFEDA100), Color(0xFFE87BA4), Color(0xFF008300), Color(0xFF6250D6), Color(0xFFE34948)),
)
private val DarkTokens = Tokens(
    buy = Color(0xFF7BD3A0), buyContainer = Color(0xFF173D2A),
    sell = Color(0xFFF0958A), sellContainer = Color(0xFF4A1D18),
    warn = Color(0xFFE3C16F), warnContainer = Color(0xFF4A3A12),
    series = listOf(Color(0xFF3987E5), Color(0xFFD95926), Color(0xFF199E70), Color(0xFFC98500), Color(0xFFD55181), Color(0xFF008300), Color(0xFF9085E9), Color(0xFFE66767)),
)

val LocalTokens = staticCompositionLocalOf { LightTokens }

private val AppTypography = Typography().let { t ->
    t.copy(
        headlineMedium = t.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
        headlineSmall = t.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
        titleLarge = t.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = t.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
        bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 21.sp),
    )
}

private val AppShapes = Shapes(
    small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(20.dp), extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun PortfolioTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalTokens provides if (dark) DarkTokens else LightTokens) {
        MaterialTheme(colorScheme = if (dark) Dark else Light, typography = AppTypography, shapes = AppShapes, content = content)
    }
}
