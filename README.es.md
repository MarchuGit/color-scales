# Color Scales

[English](README.md) · Español

**Una marca rara vez llega con una escala: llega con colores elegidos por identidad, no por sistema.**

Color Scales convierte la paleta de una marca en un set de escalas coherentes entre sí, listas para usarse juntas en un sistema de diseño.

![Tres escalas generadas: un color oscuro ubicado en el 900, dos colores fijos en una misma escala (200 y 800) y un amarillo en el 300, con el contraste WCAG en cada cuadro](docs/example.png)

## Por qué existe

Cinco o seis colores de marca casi nunca son seis escalas. Suele haber dos que comparten tono y solo cambian de luminosidad: un verde agua y un verde petróleo, un ámbar y un marrón. ¿Son la misma escala o dos? Probarlo significaba armar escalas a mano, o elegir en qué paso iba cada color y ajustar hasta que cerrara.

Color Scales lo resuelve en una línea: fija los dos colores, ubica cada uno en su nivel y dice si conviene unirlos o separarlos. Si se unen, la escala varía levemente el tono entre el claro y el oscuro, en lugar de duplicarse por diferencias sutiles.

## Qué lo hace distinto

- **Lee la luminosidad de cada color y lo ubica en su nivel.** Un color oscuro va al 900; uno claro, al 300. Todas las escalas siguen la misma curva, así el 600 de un rojo y el 600 de un azul tienen la misma luminosidad: se combinan en un sistema y el contraste entre ellas es predecible.
- **Dos colores fijos en una misma escala, con veredicto.** Si son de la misma familia, comparten escala; si no, entrega además las dos escalas separadas.
- **Los colores de marca quedan marcados.** Cada color ingresado aparece destacado en su nivel, con borde, flecha y nombre: se ve de entrada cuáles son los originales, sin tener que marcarlos a mano en Figma.
- **Extremos que se pueden usar.** El tono gira al aclarar y oscurecer como en las paletas de Tailwind: los amarillos oscuros no se vuelven aceituna y los claros no pierden identidad.

## Cuándo sirve

- Al diseñar un producto digital para una marca que ya existe.
- Al crear una marca: la paleta principal y sus escalas se definen juntas desde el inicio.

## En 30 segundos

```
4E2159
caso b C9E1D3 4C5F71
```

Una escala por línea. Sale un SVG para pegar en Figma, con los 13 niveles (`0 50 100 … 900 950 1000`) y el contraste WCAG en cada cuadro.

<details open>
<summary><h2>Todas las opciones de entrada</h2></summary>

Un color o un par de colores por línea, con o sin `#`:

```
4E2159
caso b C9E1D3 4C5F71
caso b E8F4F1 C9E1D3 fijo oscuro
caso c 592E63 9B7FA3
FFB941@400
```

| Línea | Resultado |
|---|---|
| `4E2159` | Escala de un color, ubicado por su luminosidad |
| `caso b A B` | Ambos colores fijos en una escala; si no se recomienda, también dos escalas separadas |
| `caso b A B fijo oscuro` | Un solo fijo; el paso más parecido al otro, marcado y comparado |
| `caso b A B ambos` | Une los dos colores aunque sean muy distintos |
| `caso c A B` | Degradé de A (nivel 0) a B (nivel 1000) |
| `HEX@400` | Fuerza el nivel de un color |

Se pueden pedir varias escalas a la vez, una por línea.

</details>

<details open>
<summary><h2>Cómo leer el resultado</h2></summary>

El SVG se copia al portapapeles para pegarlo en Figma con Cmd+V y se guarda además como archivo, con una vista previa.

- **Colores originales:** destacados en negro y con un nombre, centrados sobre su cuadro.
- **Contraste:** abajo a la izquierda de cada cuadro, el contraste del color con texto blanco y con texto negro según WCAG 2.1, cada uno en su propio color y solo cuando sirve: `AA Lg/UI` (3:1, texto grande e íconos o bordes), `AA` (4,5:1, texto normal) o `AAA` (7:1). Vale en los dos sentidos: la misma línea indica si sirve el texto blanco sobre el color y si sirve el color como texto o ícono sobre fondo blanco (y lo mismo con el negro).
- **Escala no recomendada:** cuando dos colores no deberían compartir escala, sus colores y su nota se marcan en rojo, y las dos escalas separadas que la reemplazan llevan ↳ en el título.
- **A pedido:** una tabla con valores HEX, OKLCH y contraste, o un reporte de desde qué nivel cada escala alcanza los mínimos de contraste para texto.

</details>

<details open>
<summary><h2>Exportar</h2></summary>

Cada escala lleva un código corto en su título (`01`, `02`…). Al pedir "exportá", la skill muestra todas las escalas de la conversación en una hoja, propone una selección (la última versión de cada color y, de una escala no recomendada, sus dos escalas separadas) y pregunta cuáles exportar, en qué formatos y si en HEX u OKLCH:

| Formato | Archivo | Para qué |
|---|---|---|
| SVG | `.svg` | Pegar en Figma |
| Variables CSS | `.css` | `--color-plum-500: #c853e6;` |
| Tokens | `.tokens.json` | Formato estándar DTCG 2025.10, para herramientas de tokens |
| Config | `.config.json` | Volver a generar exactamente las mismas escalas |

Cada conversación tiene su carpeta en Descargas (`~/Downloads/colorscales_2026-10-07_1942/`), con sus corridas y sus exportaciones adentro. El SVG exportado queda limpio: solo el nombre de cada escala.

</details>

<details open>
<summary><h2>Cómo está construida</h2></summary>

El cálculo se hace en OKLCH, un espacio de color donde los cambios numéricos se corresponden con cambios percibidos, y el contraste se mide con la fórmula de WCAG 2.1. La luminosidad de cada nivel, el giro de tono al aclarar y oscurecer, y la saturación en los extremos se calibran con las paletas de Tailwind CSS v4.3. Cuando un color pedido no existe en pantalla, se reduce su saturación sin alterar su tono ni su luminosidad. La compatibilidad de dos colores se mide como distancia perceptual en OKLab. La escala se calcula con un script: la misma entrada produce siempre el mismo resultado.

</details>

<details open>
<summary><h2>Instalación</h2></summary>

Es una skill de Claude. En Claude Code, clonar el repositorio dentro de la carpeta de skills con el nombre de la skill:

```
git clone https://github.com/MarchuGit/color-scales.git ~/.claude/skills/m-color-scales
```

Para la cuenta de claude.ai, comprimir la carpeta en un `.zip` y subirlo en la configuración de skills. Requiere Python 3. La copia al portapapeles (`pbcopy`) y la vista previa (Quick Look y Pillow) funcionan en macOS; en otros sistemas el SVG se guarda igual como archivo.

```
SKILL.md                         instrucciones para Claude
scripts/color_scale.py           motor y templates SVG
docs/example.png                 imagen de ejemplo
```

</details>

<details open>
<summary><h2>Límites</h2></summary>

No elige los colores de una marca ni reemplaza el criterio visual en los casos límite: la recomendación de unir o separar una escala usa umbrales orientativos. La vista previa usa fuentes de reemplazo; el SVG conserva las tipografías del diseño (Geist y Andale Mono). Todavía no genera modo oscuro ni neutros con tinte.

</details>

## Créditos y licencia

La curva de luminosidad, el giro de tono y la caída de saturación en los extremos se calibraron con la paleta de colores de [Tailwind CSS](https://tailwindcss.com) v4.3, de Tailwind Labs, Inc., publicada bajo licencia MIT.

[MIT](LICENSE) © 2026 Marcela Gómez
