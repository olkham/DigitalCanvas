import base64
import requests

class DisplayNowTestCase():
    def __init__(self, host, *args, **kwargs):
        self.host = host

    def test_display_now(self, filename):
        # Create a base64 encoded image string
        image = open(filename, 'rb').read()
        image_data = base64.b64encode(image).decode('utf-8')
        
        # Send a POST request to the /display_now endpoint
        response = requests.post(f'{self.host}/display_now', data={'image': image_data})
        print(response.text)
        
    #function to send a file to the /display_now endpoint
    def upload_file(self, filename):
        with open(filename, 'rb') as file:
            response = requests.post(f'{self.host}/display_now', files={'file': file})
            print(response.text)
    

if __name__ == '__main__':
    test = DisplayNowTestCase('http://192.168.1.183:7000')
    # test.test_display_now('test_image.jpg')
    test.upload_file('test_image.jpg')