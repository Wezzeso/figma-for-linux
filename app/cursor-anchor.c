/* Figma-only Xcursor filter: stable arrow tip with a live resize-direction badge.
 * This changes cursor artwork only. It never reads or changes pointer position,
 * input events, button state, browser content, or document geometry.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Stable public libXcursor ABI; no development package is needed at runtime. */
typedef struct _XDisplay Display;
typedef unsigned long Cursor;
typedef struct {
    uint32_t version, size, width, height, xhot, yhot, delay;
    uint32_t *pixels;
} XcursorImage;

#include "cursor-arrow.h"

static int is_resize_arrow(const XcursorImage *image)
{
    if (!image || !image->pixels || image->width != 32 || image->height != 32 ||
        image->xhot != 16 || image->yhot != 16)
        return 0;

    /* Double-ended arrows are thin, centered, and strongly directional. Hand,
     * rotation, eyedropper, pen, text, and ordinary arrow cursors are excluded.
     * Measuring the principal axis also supports rotated selection bounds.
     */
    double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    unsigned n = 0;
    for (unsigned y = 0; y < 32; ++y) {
        for (unsigned x = 0; x < 32; ++x) {
            if ((image->pixels[y * 32 + x] >> 24) <= 180)
                continue;
            ++n;
            sx += x; sy += y;
            sxx += x * x; syy += y * y; sxy += x * y;
        }
    }
    if (n < 60 || n > 220)
        return 0;
    double mx = sx / n, my = sy / n;
    if (fabs(mx - 15.5) > 2.0 || fabs(my - 15.5) > 2.0)
        return 0;
    double xx = sxx / n - mx * mx, yy = syy / n - my * my;
    double xy = sxy / n - mx * my;
    double trace = xx + yy, delta = hypot(xx - yy, 2 * xy);
    return trace > delta && (trace + delta) / (trace - delta) >= 5.5;
}

static uint32_t over(uint32_t src, uint32_t dst)
{
    unsigned inverse = 255 - (src >> 24);
    uint32_t value = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) {
        unsigned channel = ((src >> shift) & 255) +
            ((((dst >> shift) & 255) * inverse + 127) / 255);
        value |= (channel > 255 ? 255 : channel) << shift;
    }
    return value;
}

int figma_patch_cursor(const XcursorImage *image, XcursorImage *patched,
                       uint32_t output[1024])
{
    if (!is_resize_arrow(image))
        return 0;
    memcpy(output, figma_arrow, sizeof(figma_arrow));
    /* Keep the direction artwork live, using an antialiased 16px badge. */
    for (unsigned y = 0; y < 16; ++y) {
        for (unsigned x = 0; x < 16; ++x) {
            uint32_t pixel = 0;
            for (unsigned shift = 0; shift < 32; shift += 8) {
                unsigned sum = 0;
                for (unsigned dy = 0; dy < 2; ++dy)
                    for (unsigned dx = 0; dx < 2; ++dx)
                        sum += (image->pixels[(y * 2 + dy) * 32 + x * 2 + dx] >> shift) & 255;
                pixel |= ((sum + 2) / 4) << shift;
            }
            unsigned dest = (y + 16) * 32 + x + 16;
            output[dest] = over(pixel, output[dest]);
        }
    }
    *patched = *image;
    patched->xhot = patched->yhot = 4;
    patched->pixels = output;
    return 1;
}

Cursor XcursorImageLoadCursor(Display *display, const XcursorImage *image)
{
    typedef Cursor (*LoadCursor)(Display *, const XcursorImage *);
    LoadCursor real_load = (LoadCursor)dlsym(RTLD_NEXT, "XcursorImageLoadCursor");
    if (!real_load)
        return 0;
    XcursorImage patched;
    uint32_t pixels[1024];
    if (!figma_patch_cursor(image, &patched, pixels))
        return real_load(display, image);
    if (getenv("FIGMA_CURSOR_TRACE"))
        fprintf(stderr, "Figma: anchored resize cursor, retaining direction feedback\n");
    return real_load(display, &patched);
}
