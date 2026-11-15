"""Short isolated Qt/OpenGL frame check, run only by the local panel launcher."""
import sys
from PyQt6.QtCore import QLoggingCategory, QTimer, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication, QWidget


def main():
    messages = []
    qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    QLoggingCategory.setFilterRules('qt.rhi.general.debug=true\nqt.qpa.backingstore.debug=true')
    app = QApplication([])
    window = QWidget()
    window.setStyleSheet('background: rgb(7, 20, 38);')
    window.resize(64, 64)
    window.show()

    def check():
        # Read the displayed frame, not QWidget.grab() (which repaints in software).
        image = app.primaryScreen().grabWindow(int(window.winId())).toImage()
        good = not image.isNull()
        if good:
            pixel = image.pixelColor(image.width() // 2, image.height() // 2)
            good = (pixel.red(), pixel.green(), pixel.blue()) == (7, 20, 38)
        # Qt can internally fall back to raster on RHI creation failure.
        failed = any('failed' in message.lower() or 'not supported' in message.lower()
                     for message in messages)
        created = any('Created OpenGL context' in message for message in messages)
        composed = any('Composing and flushing' in message and 'via swapchain' in message
                       for message in messages)
        if good and created and composed and not failed:
            print('AIRLINK_GL_FRAME_OK', flush=True)
            app.exit(0)
        else:
            app.exit(1)

    QTimer.singleShot(250, check)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
