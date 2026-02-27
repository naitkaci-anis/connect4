# main.py
from controller import Controller
from view_tk import TkView


def main():
    view = TkView()
    controller = Controller(view)
    view.set_controller(controller)
    controller.start()
    view.mainloop()


if __name__ == "__main__":
    main()
