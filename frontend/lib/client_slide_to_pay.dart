import 'package:flutter/material.dart';
import 'app_language.dart';

class ClientSlideToPay extends StatefulWidget {
  final VoidCallback? onConfirmed;
  const ClientSlideToPay({super.key, this.onConfirmed});

  @override
  State<ClientSlideToPay> createState() => _ClientSlideToPayState();
}

class _ClientSlideToPayState extends State<ClientSlideToPay> {
  double progress = 0;
  bool pointerInteraction = false, cancelled = false, completed = false;

  @override
  void didUpdateWidget(ClientSlideToPay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.onConfirmed == null || oldWidget.onConfirmed == null) {
      progress = 0;
      completed = false;
      pointerInteraction = false;
    }
  }

  void finish(double value) {
    if (widget.onConfirmed == null || completed || cancelled) return;
    final confirm = value >= .98;
    setState(() {
      completed = confirm;
      // Keyboard and screen-reader increments retain progress until completion.
      progress = confirm
          ? 1
          : pointerInteraction
          ? 0
          : value;
      pointerInteraction = false;
    });
    if (confirm) widget.onConfirmed?.call();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onConfirmed != null && !completed;
    return Directionality(
      textDirection: TextDirection.ltr,
      child: Listener(
        onPointerDown: (_) {
          pointerInteraction = true;
          cancelled = false;
        },
        onPointerCancel: (_) => setState(() {
          cancelled = true;
          pointerInteraction = false;
          progress = 0;
        }),
        child: SizedBox(
          height: 60,
          child: Stack(
            alignment: Alignment.center,
            children: [
              SliderTheme(
                data: SliderTheme.of(context).copyWith(
                  trackHeight: 48,
                  activeTrackColor: Colors.white.withValues(alpha: .28),
                  inactiveTrackColor: Colors.white.withValues(alpha: .12),
                  disabledActiveTrackColor: Colors.white10,
                  disabledInactiveTrackColor: Colors.white10,
                  thumbColor: Colors.white,
                  disabledThumbColor: Colors.white38,
                  thumbShape: const _PayThumb(),
                  overlayShape: const RoundSliderOverlayShape(
                    overlayRadius: 26,
                  ),
                  overlayColor: Colors.white12,
                  showValueIndicator: ShowValueIndicator.never,
                ),
                child: Slider(
                  padding: const EdgeInsets.symmetric(horizontal: 26),
                  value: progress,
                  allowedInteraction: SliderInteraction.slideThumb,
                  semanticFormatterCallback: (value) =>
                      '${tr('Slide to the right to pay')}, ${(value * 100).round()}%',
                  onChanged: enabled
                      ? (value) => setState(() => progress = value)
                      : null,
                  onChangeStart: enabled ? (_) => cancelled = false : null,
                  onChangeEnd: enabled ? finish : null,
                ),
              ),
              IgnorePointer(
                child: ExcludeSemantics(
                  child: AnimatedOpacity(
                    opacity: progress > .05
                        ? 0
                        : enabled
                        ? 1
                        : .5,
                    duration: const Duration(milliseconds: 120),
                    child: Padding(
                      padding: const EdgeInsets.only(left: 56, right: 12),
                      child: AppText(
                        'Slide to the right to pay',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PayThumb extends RoundSliderThumbShape {
  const _PayThumb()
    : super(
        enabledThumbRadius: 23,
        disabledThumbRadius: 23,
        elevation: 0,
        pressedElevation: 2,
      );

  @override
  void paint(
    PaintingContext context,
    Offset center, {
    required Animation<double> activationAnimation,
    required Animation<double> enableAnimation,
    required bool isDiscrete,
    required TextPainter labelPainter,
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required TextDirection textDirection,
    required double value,
    required double textScaleFactor,
    required Size sizeWithOverflow,
  }) {
    super.paint(
      context,
      center,
      activationAnimation: activationAnimation,
      enableAnimation: enableAnimation,
      isDiscrete: isDiscrete,
      labelPainter: labelPainter,
      parentBox: parentBox,
      sliderTheme: sliderTheme,
      textDirection: textDirection,
      value: value,
      textScaleFactor: textScaleFactor,
      sizeWithOverflow: sizeWithOverflow,
    );
    final arrow = Path()
      ..moveTo(center.dx - 7, center.dy)
      ..lineTo(center.dx + 7, center.dy)
      ..moveTo(center.dx + 1, center.dy - 6)
      ..lineTo(center.dx + 7, center.dy)
      ..lineTo(center.dx + 1, center.dy + 6);
    context.canvas.drawPath(
      arrow,
      Paint()
        ..color = const Color(0xff163456)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }
}
